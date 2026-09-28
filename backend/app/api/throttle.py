"""Slowing down password guessing on the public sign-in (audit D-06).

Kept in this process's memory (one API process serves the estate). Every attempt is
booked before its password is checked, and a booked one counts like a wrong one, so
a burst of requests sent all at once is held just as the same requests one after
another would be.

* One place, one email: a growing wait after a few wrong passwords (2 s, 4 s, 8 s ...
  up to a minute), and one check at a time. It is keyed on the email *and* the
  place, so a guesser somewhere else never holds the owner up.
* One place, any email: 20 wrong passwords in 15 minutes, then that place waits
  until the oldest of them is 15 minutes old; and at most a few checks at once, so
  one place can't tie up the server's workers waiting for a turn to hash.
* One email, from everywhere: a guesser with many addresses gets 50 wrong passwords
  an hour at one email, then new phones wait. A phone that has signed in with that
  email before carries a known-phone mark (app.core.security.phone_token) and isn't
  held by this, so a crowd guessing the owner's email can't keep the owner out.

Never a lockout: every wait ends, and the right password afterwards works as always.
A held attempt never checks the password, so it costs no Argon2 hashing either; and
at most a few hashes run at once (HASHING), because each takes 64 MB and a flood of
them in parallel could starve the server of memory.

The place: production sits behind a Cloudflare tunnel, so every request reaches the
API from the tunnel's own local address; the visitor's is in CF-Connecting-IP, which
is believed only when the request came from the tunnel (TRUSTED_PROXIES). Believed
from anyone, a guesser would just make up a new one each time. serve.py runs uvicorn
without its own X-Forwarded-For rewrite so this sees the real peer. An IPv6 address
counts by its /64, the block a single home or phone is given.
"""
from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger
from app.i18n import t

log = get_logger(__name__)

IP_WINDOW_S = 15 * 60
IP_LIMIT = 20
IP_AT_ONCE = 3  # password checks in progress from one place
FREE_TRIES = 3  # wrong passwords from one place for one email before any wait
MAX_WAIT_S = 60
FORGET_S = 60 * 60  # one place, one email: this long with no wrong password starts afresh
EMAIL_WINDOW_S = 60 * 60
EMAIL_LIMIT = 200  # wrong passwords an hour at one email from everywhere, new phones
MAX_KEYS = 10_000  # places and emails remembered, at most

# Password checks running at once, and how long a sign-in waits for its turn.
HASHING = threading.BoundedSemaphore(4)
HASH_WAIT_S = 5

SOON_S = 2  # "try again in a few seconds"


def client_ip(request: Request) -> str:
    """The visitor's address: CF-Connecting-IP (or the last X-Forwarded-For hop) when
    the request came through the tunnel, a trusted peer; else the address that
    connected. From anyone else those headers are anyone's to write."""
    peer = request.client.host if request.client else ""
    if peer in settings.trusted_proxies:
        forwarded = _forwarded(request)
        if forwarded:
            return forwarded
    elif _from_cloudflare(request):
        _untrusted_tunnel(peer)
    return peer or "unknown"


def from_outside(request: Request) -> bool:
    """Whether a request came from the internet: through the tunnel (or another
    trusted proxy), or straight from a public address. The server's own network,
    the LAN or the machine itself, is not.

    Cloudflare's own headers (CF-Connecting-IP, CF-Ray) mean the internet, whoever
    the peer is: a tunnel that reaches the API by the machine's LAN address would
    otherwise make every visitor look local and let the published admin password in.
    Somebody on the LAN who writes them only locks themselves out of that."""
    peer = request.client.host if request.client else ""
    if peer in settings.trusted_proxies and _forwarded(request):
        return True
    if _from_cloudflare(request):
        _untrusted_tunnel(peer)
        return True
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global


def _from_cloudflare(request: Request) -> bool:
    return bool(request.headers.get("cf-connecting-ip") or request.headers.get("cf-ray"))


_warned: set[str] = set()


def _untrusted_tunnel(peer: str) -> None:
    """Say once per peer that Cloudflare's requests come from one TRUSTED_PROXIES
    doesn't name: every visitor then counts as that one address in the sign-in
    limits, so 20 wrong passwords from anyone hold everyone for 15 minutes."""
    if peer in _warned or len(_warned) > 100:
        return
    _warned.add(peer)
    log.warning("throttle.untrusted_tunnel", peer=peer,
                trusted_proxies=list(settings.trusted_proxies),
                fix="point the tunnel at http://localhost:8090, or add this address "
                    "to TRUSTED_PROXIES in backend/.env")


def _forwarded(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
    return next((h for h in reversed(hops) if h), "")


def place_of(ip: str) -> str:
    """The key an address counts under: itself, or its /64 for IPv6."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def wait_for(failures: int) -> int:
    """Seconds one place waits for an email after `failures` wrong passwords in a row."""
    if failures < FREE_TRIES:
        return 0
    return min(MAX_WAIT_S, 2 ** (failures - FREE_TRIES + 1))


@dataclass
class _Place:
    wrong: deque = field(default_factory=lambda: deque(maxlen=IP_LIMIT))
    checking: int = 0


@dataclass
class _Pair:  # one place, one email
    failures: int = 0
    last: float = 0.0
    checking: bool = False


@dataclass
class _Email:  # one email, from everywhere
    wrong: deque = field(default_factory=lambda: deque(maxlen=EMAIL_LIMIT))
    checking: int = 0


class Attempt:
    """One booked sign-in. Say how it went (`failed`, `succeeded`); left unsaid (the
    server was busy, the database went away) it is let go and counts for nothing."""

    def __init__(self, throttle: LoginThrottle, place: str, email: str) -> None:
        self._throttle, self.place, self.email = throttle, place, email
        self._done = False

    def failed(self) -> None:
        self._finish("wrong")

    def succeeded(self) -> None:
        self._finish("right")

    def _finish(self, outcome: str) -> None:
        if not self._done:
            self._done = True
            self._throttle._finish(self.place, self.email, outcome)

    def __enter__(self) -> Attempt:
        return self

    def __exit__(self, *exc) -> None:
        self._finish("none")


@dataclass
class LoginThrottle:
    clock: Callable[[], float] = time.monotonic
    _places: dict[str, _Place] = field(default_factory=dict)
    _pairs: dict[tuple[str, str], _Pair] = field(default_factory=dict)
    _emails: dict[str, _Email] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def attempt(self, ip: str, email: str, *, known: bool = False) -> Attempt:
        """Book a sign-in for `email` from `ip`, or raise 429 with a Retry-After if it
        has to wait. `known`: the phone has signed in with this email before."""
        now = self.clock()
        key = place_of(ip)
        with self._lock:
            self._trim(now)
            place = self._places.get(key) or _Place()
            _expire(place.wrong, now - IP_WINDOW_S)
            if len(place.wrong) + place.checking >= IP_LIMIT:
                wait = IP_WINDOW_S - (now - place.wrong[0]) if place.wrong else SOON_S
                raise _too_many(t("throttle.place", wait=_minutes(wait)), wait)
            if place.checking >= IP_AT_ONCE:
                raise _too_many(t("throttle.at_once"), SOON_S)

            pair = self._pairs.get((key, email))
            if pair is not None and not pair.checking and now - pair.last >= FORGET_S:
                del self._pairs[(key, email)]
                pair = None
            if pair is not None:
                if pair.checking:
                    raise _too_many(t("throttle.checking"), SOON_S)
                wait = math.ceil(wait_for(pair.failures) - (now - pair.last))
                if wait > 0:
                    raise _too_many(t("throttle.email", n=wait), wait)

            everywhere = self._emails.get(email) or _Email()
            _expire(everywhere.wrong, now - EMAIL_WINDOW_S)
            if not known and len(everywhere.wrong) + everywhere.checking >= EMAIL_LIMIT:
                wait = (EMAIL_WINDOW_S - (now - everywhere.wrong[0]) if everywhere.wrong
                        else SOON_S)
                raise _too_many(t("throttle.email_lately", wait=_minutes(wait)), wait)

            place.checking += 1
            self._places[key] = place
            pair = pair or _Pair()
            pair.checking = True
            self._pairs[(key, email)] = pair
            everywhere.checking += 1
            self._emails[email] = everywhere
        return Attempt(self, key, email)

    def _finish(self, key: str, email: str, outcome: str) -> None:
        now = self.clock()
        wrong = outcome == "wrong"
        with self._lock:
            place = self._places.setdefault(key, _Place()) if wrong else self._places.get(key)
            if place is not None:
                place.checking = max(0, place.checking - 1)
                if wrong:
                    place.wrong.append(now)
            pair = (self._pairs.setdefault((key, email), _Pair()) if wrong
                    else self._pairs.get((key, email)))
            if pair is not None:
                pair.checking = False
                if wrong:
                    pair.failures += 1
                    pair.last = now
                elif outcome == "right":
                    del self._pairs[(key, email)]
            everywhere = (self._emails.setdefault(email, _Email()) if wrong
                          else self._emails.get(email))
            if everywhere is not None:
                everywhere.checking = max(0, everywhere.checking - 1)
                if wrong:
                    everywhere.wrong.append(now)

    def reset(self) -> None:
        with self._lock:
            self._places.clear()
            self._pairs.clear()
            self._emails.clear()

    def _trim(self, now: float) -> None:
        """Forget old entries once there are many, so a flood of made-up emails and
        addresses can't grow this without end. Nothing being checked is forgotten."""
        if len(self._places) + len(self._pairs) + len(self._emails) < MAX_KEYS:
            return
        for k in [k for k, v in self._places.items()
                  if not v.checking and (not v.wrong or now - v.wrong[-1] >= IP_WINDOW_S)]:
            del self._places[k]
        for k in [k for k, v in self._pairs.items() if not v.checking and now - v.last >= FORGET_S]:
            del self._pairs[k]
        for k in [k for k, v in self._emails.items()
                  if not v.checking and (not v.wrong or now - v.wrong[-1] >= EMAIL_WINDOW_S)]:
            del self._emails[k]
        # Still full of fresh ones: drop the oldest half rather than grow.
        for store in (self._places, self._pairs, self._emails):
            if len(store) >= MAX_KEYS // 3:
                idle = [k for k, v in store.items() if not v.checking]
                for k in idle[: len(store) // 2]:
                    del store[k]


def _expire(times: deque, before: float) -> None:
    while times and times[0] <= before:
        times.popleft()


def _minutes(seconds: float) -> str:
    return t("count.minutes", n=max(1, math.ceil(seconds / 60)))


def _too_many(detail: str, wait: float) -> HTTPException:
    return HTTPException(429, detail, headers={"Retry-After": str(max(1, math.ceil(wait)))})


throttle = LoginThrottle()
