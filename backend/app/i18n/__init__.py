"""What the server says to people, in their language: English (the default),
Finnish, Swedish, Norwegian (bokmål) and Spanish.

Every sentence a person can read (Tonight's verdicts and "why", camera health, the
activity read, insights, alerts, errors, check results, pushes) is a key in the
catalogs here, one module per language, and is written with

    tr(lang, "tonight.seen_at_camera", species=..., n=..., total=...)

or, inside a request, t(key, ...) in the language the request is in: the signed-in
person's own (users.language), else the Accept-Language the app sends (the sign-in
page, a 401), else English. A push is written in its RECIPIENT's language, whoever's
request or scheduled run sends it: `with use(person.language): ...`.

A message is a str.format template, or {"one": ..., "other": ...} for one that
depends on a number, which is the parameter `n`. English is the fallback for a key
a catalog lacks; tests keep every catalog complete, with the same placeholders.
"""
from __future__ import annotations

import contextlib
import re
import string
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import date, datetime
from functools import lru_cache

LANGUAGES = ("en", "fi", "sv", "nb", "es")
DEFAULT = "en"
# What a person may be set to, as the PATCH and the database check take it.
NAMES = {"en": "English", "fi": "Suomi", "sv": "Svenska", "nb": "Norsk (bokmål)", "es": "Español"}

# Tags a browser or phone sends that mean one of ours: Norwegian as "no" or nynorsk
# reads bokmål better than English.
_ALIASES = {"no": "nb", "nn": "nb"}


class _Now:
    """The language of what is being written now. One per request: the dependency
    that finds the signed-in person changes it in place, which the endpoint (run in
    another thread, on a copy of the context) sees."""

    __slots__ = ("lang",)

    def __init__(self, lang: str) -> None:
        self.lang = lang


_current: ContextVar[_Now | None] = ContextVar("gamesense_language", default=None)


def normalize(code: str | None) -> str | None:
    """One of LANGUAGES for a language tag ("sv-FI" -> "sv", "no" -> "nb"), or None."""
    if not code:
        return None
    base = code.strip().lower().replace("_", "-").split("-")[0]
    base = _ALIASES.get(base, base)
    return base if base in LANGUAGES else None


def from_accept_language(header: str | None) -> str:
    """The best of ours in an Accept-Language header ("fi-FI,fi;q=0.9,en;q=0.8"), by
    its weights; English when it names none of them."""
    if not header:
        return DEFAULT
    best, best_q = None, -1.0
    for i, part in enumerate(header.split(",")):
        tag, _, rest = part.strip().partition(";")
        q = 1.0
        m = re.search(r"q\s*=\s*([0-9.]+)", rest)
        if m:
            try:
                q = float(m.group(1))
            except ValueError:
                q = 0.0
        lang = normalize(tag)
        # Earlier wins a tie, as the header lists them in the order wanted.
        if lang and q > 0 and q > best_q:
            best, best_q = lang, q
    return best or DEFAULT


def current() -> str:
    """The language being written in: the request's, a push's recipient's, or English."""
    now = _current.get()
    return now.lang if now is not None else DEFAULT


def set_current(lang: str | None) -> None:
    """Write in `lang` from here on in this request (or run). Unknown: left as it was."""
    lang = normalize(lang)
    if lang is None:
        return
    now = _current.get()
    if now is None:
        _current.set(_Now(lang))
    else:
        now.lang = lang


@contextlib.contextmanager
def use(lang: str | None) -> Iterator[str]:
    """Write in `lang` inside the block (a push to one person), then as before."""
    token = _current.set(_Now(normalize(lang) or DEFAULT))
    try:
        yield current()
    finally:
        _current.reset(token)


def _catalog(lang: str) -> dict:
    from app.i18n import en, es, fi, nb, sv

    return {"en": en, "fi": fi, "sv": sv, "nb": nb, "es": es}[lang].MESSAGES


def plural(lang: str, n: int | float) -> str:
    """"one" or "other": the forms all five languages have for counting things."""
    return "one" if n == 1 else "other"


def _template(lang: str, key: str, n) -> str | None:
    msg = _catalog(lang).get(key)
    if isinstance(msg, dict):
        form = plural(lang, n) if n is not None else "other"
        msg = msg.get(form) or msg.get("other")
    return msg


def tr(lang: str | None, key: str, **params) -> str:
    """The message `key` in `lang`, with `params` filled in. English where `lang`'s
    catalog has no such key; the key itself if neither has it (a bug the catalog
    tests catch, never a crash in front of a hunter)."""
    lang = normalize(lang) or DEFAULT
    n = params.get("n")
    for code in (lang, DEFAULT):
        text = _template(code, key, n)
        if text is None:
            continue
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            continue
    return key


def t(key: str, **params) -> str:
    """tr() in the language being written in (current())."""
    return tr(current(), key, **params)


def stored(key: str, **params) -> str:
    """The English text of `key`, for a message kept in the database for everyone (a
    camera's fetch error, a login's last error): put in each reader's language when
    read (localize). `key` is one of en.STORED."""
    return tr(DEFAULT, key, **params)


def has(key: str) -> bool:
    return key in _catalog(DEFAULT)


def reading_order(lang: str | None = None) -> list[str]:
    """The languages to read a word the app sent back in (a class it was shown, as a
    filter), one at a time: the reader's own, then English (an older link, a saved
    filter), then the rest. The first that knows the word says what it means; two
    languages are never mixed, as they share words for different things ("Hjort"
    is a stag in Swedish and a red deer in Norwegian)."""
    first = normalize(lang) or current()
    return list(dict.fromkeys((first, DEFAULT, *LANGUAGES)))


class LanguageMiddleware:
    """Each request is written in the Accept-Language the app sent, until the
    signed-in person's own language takes over (api.deps.get_current_user). Plain
    ASGI, so the language is set in the context the endpoint and its errors run in."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        header = None
        for name, value in scope.get("headers") or ():
            if name == b"accept-language":
                header = value.decode("latin-1")
                break
        token = _current.set(_Now(from_accept_language(header)))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


# ---- words every screen uses --------------------------------------------------------

def join(names: list[str], lang: str | None = None) -> str:
    """"A", "A and B", "A, B and C", "A, B and 2 more", in the language."""
    lang = lang or current()
    names = [str(x) for x in names]
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return tr(lang, "list.two", a=names[0], b=names[1])
    if len(names) == 3:
        return tr(lang, "list.three", a=names[0], b=names[1], c=names[2])
    return tr(lang, "list.more", a=names[0], b=names[1], n=len(names) - 2)


def join_all(names: list[str], lang: str | None = None) -> str:
    """Every name, the last two with "and": "A, B, C and D"."""
    lang = lang or current()
    names = [str(x) for x in names]
    if len(names) <= 1:
        return names[0] if names else ""
    return tr(lang, "list.two", a=", ".join(names[:-1]), b=names[-1])


def decimal(x: float, digits: int = 1, lang: str | None = None) -> str:
    """"1.5" in English, "1,5" in the others: the language's decimal mark. A whole
    number drops its ".0"."""
    text = f"{x:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", tr(lang or current(), "num.decimal_mark"))


def fixed(x: float, digits: int = 1, lang: str | None = None) -> str:
    """"2.0" / "2,0": always `digits` decimals, in the language's decimal mark."""
    return f"{x:.{digits}f}".replace(".", tr(lang or current(), "num.decimal_mark"))


def weekday(d: date | datetime, lang: str | None = None, *, short: bool = True) -> str:
    """"Thu" / "Thursday" in the language (Monday is 0, as date.weekday())."""
    return tr(lang or current(), f"cal.{'wd' if short else 'wdl'}.{d.weekday()}")


def month(d: date | datetime | int, lang: str | None = None, *, short: bool = True) -> str:
    """"Sep" / "September" in the language."""
    m = d if isinstance(d, int) else d.month
    return tr(lang or current(), f"cal.{'mon' if short else 'monl'}.{m}")


def day_month(d: date | datetime, lang: str | None = None) -> str:
    """"24 Sep", "24.9.", "24 sep." as a hunter writes a date in that language."""
    lang = lang or current()
    return tr(lang, "cal.day_month", day=d.day, month=month(d, lang), m=d.month)


def weekday_day_month(d: date | datetime, lang: str | None = None) -> str:
    """"Thu 24 Sep" in the language."""
    lang = lang or current()
    return tr(lang, "cal.wd_day_month", wd=weekday(d, lang), day=d.day,
              month=month(d, lang), m=d.month)


# ---- species ------------------------------------------------------------------------

def species_name(species_id: str | None, stored: str | None = None,
                 lang: str | None = None) -> str:
    """What to call a species in the language: the catalog's name for it, unless an
    admin renamed it in Settings, and then that name, in every language.

    `stored` is species.common_name. It is the admin's own when it is not the name
    the species started with (app.ai.classifier.default_name, or the title-case one
    an older build stored); written as a sentence starts ("Iberian ibex").
    """
    lang = lang or current()
    if species_id and not renamed(species_id, stored):
        key = f"species.{species_id}"
        if key in _catalog(DEFAULT):
            return tr(lang, key)
    if stored:
        return stored[:1].upper() + stored[1:]
    return species_id or tr(lang, "class.animal")


# Languages that write an animal's name in lower case inside a sentence
# ("villisika", "jabalí"): all but English, which writes "Wild boar" as it always has.
_LOWER_INSIDE = frozenset({"fi", "sv", "nb", "es"})


def species_inside(species_id: str | None, stored: str | None = None,
                   lang: str | None = None) -> str:
    """species_name as a word inside a sentence, or after the first name of a list
    ("Villisika, saksanhirvi ja 2 muuta"): lower case in a language that writes it
    so. An admin's own name is written as they wrote it, in every language."""
    lang = lang or current()
    name = species_name(species_id, stored, lang)
    if (lang in _LOWER_INSIDE and species_id and not renamed(species_id, stored)
            and f"species.{species_id}" in _catalog(DEFAULT)):
        return name[:1].lower() + name[1:]
    return name


def renamed(species_id: str, stored: str | None) -> bool:
    """Whether `stored` (species.common_name) is a name an admin gave it."""
    if not stored:
        return False
    return stored.strip().lower() not in _default_names(species_id)


@lru_cache(maxsize=256)
def _default_names(species_id: str) -> frozenset[str]:
    from app.ai.classifier import default_name

    names = {default_name(species_id).lower(), species_id.replace("_", " ").lower()}
    en = _catalog(DEFAULT).get(f"species.{species_id}")
    if isinstance(en, str):
        names.add(en.lower())
    return frozenset(names)


# ---- text kept in the database in English -------------------------------------------

_FORMATTER = string.Formatter()


@lru_cache(maxsize=1)
def _stored_patterns() -> list[tuple[re.Pattern, str, tuple[str, ...]]]:
    """The English templates of messages the server keeps as text (a camera's fetch
    error, a login's last error), as patterns that find the key and its values again."""
    from app.i18n.en import STORED

    out = []
    for key in STORED:
        msg = _catalog(DEFAULT)[key]
        for form in (msg.values() if isinstance(msg, dict) else (msg,)):
            names: list[str] = []
            pattern = ""
            for literal, field, _, _ in _FORMATTER.parse(form):
                pattern += re.escape(literal)
                if field is not None:
                    if field in names:
                        pattern += f"(?P={field})"
                    else:
                        names.append(field)
                        pattern += f"(?P<{field}>.+?)"
            literal = sum(len(lit) for lit, _, _, _ in _FORMATTER.parse(form))
            out.append((literal, re.compile(f"^{pattern}$", re.S), key, tuple(names)))
    # The most words first: "Couldn't reach {provider}. It tries again ..." before
    # "{text}. It tries again ...", which would take it too.
    out.sort(key=lambda p: -p[0])
    return [p[1:] for p in out]


# Parameters of kept messages that are decimal numbers (fetch.disk_full's free GB).
_DECIMAL_PARAMS = frozenset({"gb"})


def localize(text: str | None, lang: str | None = None) -> str | None:
    """A message the server kept in English (en.STORED), said in the language.

    A camera's fetch error or a login's last error is written when the fetch runs,
    for everyone; it is put in the reader's language when read. Anything else (a
    provider's own words, an older message) comes back as it was."""
    if not text:
        return text
    lang = lang or current()
    if lang == DEFAULT:
        return text
    for pattern, key, names in _stored_patterns():
        m = pattern.match(text)
        if m:
            # A value can be a kept message itself ("Photos not coming in. {error}").
            params = {k: localize(v, lang) for k, v in m.groupdict().items()}
            if "n" in params:
                with contextlib.suppress(ValueError):
                    params["n"] = int(params["n"])
            for k in _DECIMAL_PARAMS & params.keys():
                # A number kept as English text ("12.3" GB free), in the language's mark.
                if re.fullmatch(r"\d+\.\d+", params[k]):
                    params[k] = params[k].replace(".", tr(lang, "num.decimal_mark"))
            return tr(lang, key, **params)
    return text


__all__ = [
    "DEFAULT", "LANGUAGES", "NAMES", "LanguageMiddleware", "current", "day_month", "decimal",
    "fixed", "from_accept_language", "join", "join_all", "localize", "month", "normalize",
    "plural", "reading_order", "renamed", "set_current", "species_inside", "species_name",
    "stored", "t", "tr", "use", "weekday", "weekday_day_month",
]
