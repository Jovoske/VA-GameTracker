"""Five languages (round 8): English, Finnish, Swedish, Norwegian bokmål, Spanish.

Everything the server says to a person comes from app/i18n: the signed-in person's
language, else the Accept-Language the phone sends (the sign-in page, a 401), else
English, which reads exactly as it did before. A push is written in the language of
the person it goes to, whoever's run sends it. What is kept in the database (a
login's last problem, a fetch's error) is kept in English and read back in the
reader's language.
"""
from __future__ import annotations

import re
import string
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.api import throttle as throttle_mod
from app.core import crypto
from app.core.security import create_access_token, hash_password
from app.i18n import LANGUAGES, from_accept_language, localize, stored, tr, use
from app.i18n import en as en_catalog
from app.ingestion import logins
from app.models import (
    Camera,
    CameraAccount,
    Detection,
    Estate,
    Image,
    Notification,
    NotificationPref,
    Species,
    Stand,
    User,
    Zone,
)
from app.notifications import dispatch, hold, plan, push

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
PASSWORD = "a-good-long-password"
_F = string.Formatter()


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in _F.parse(text) if name is not None}


# ── the catalogs ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", LANGUAGES[1:])
def test_every_key_is_in_every_catalog_with_the_same_placeholders(lang):
    en, other = i18n._catalog("en"), i18n._catalog(lang)
    assert sorted(set(en) - set(other)) == [], "missing in " + lang
    assert sorted(set(other) - set(en)) == [], "not in English"
    for key, text in en.items():
        theirs = other[key]
        assert type(theirs) is type(text), key
        if isinstance(text, dict):
            # A count: the same two forms, each with what the English form has.
            assert set(theirs) == set(text) == {"one", "other"}, key
            for form in text:
                assert _fields(theirs[form]) == _fields(text[form]), (key, form)
                assert theirs[form].strip(), (key, form)
        else:
            assert _fields(theirs) == _fields(text), key
            assert theirs.strip(), key


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_message_can_be_written(lang):
    """Each one formats with its parameters: no stray brace, no unknown field."""
    for key, text in i18n._catalog(lang).items():
        forms = text.values() if isinstance(text, dict) else [text]
        params = {name: 2 for form in forms for name in _fields(form)}
        params.setdefault("n", 2)
        out = tr(lang, key, **params)
        assert out != key and "{" not in out and "}" not in out, (lang, key, out)


@pytest.mark.parametrize("lang", LANGUAGES[1:])
def test_the_catalogs_are_translated_not_copied(lang):
    """Some words are the same in both (Admin, km/h, a clock): most are not."""
    en, other = i18n._catalog("en"), i18n._catalog(lang)
    same = [k for k in en if en[k] == other[k]]
    assert len(same) < len(en) * 0.05, same


def test_what_is_kept_in_english_is_in_the_catalog():
    for key in en_catalog.STORED:
        assert key in en_catalog.MESSAGES, key


@pytest.mark.parametrize(("lang", "names"), [
    ("en", ["Wild boar", "Red deer", "Roe deer", "Fallow deer"]),
    ("fi", ["Villisika", "Saksanhirvi", "Metsäkauris", "Kuusipeura"]),
    ("sv", ["Vildsvin", "Kronhjort", "Rådjur", "Dovhjort"]),
    ("nb", ["Villsvin", "Hjort", "Rådyr", "Dåhjort"]),
    ("es", ["Jabalí", "Ciervo", "Corzo", "Gamo"]),
])
def test_the_animals_have_their_hunters_names(lang, names):
    ids = ["wild_boar", "red_deer", "roe_deer", "fallow_deer"]
    assert [i18n.species_name(s, None, lang) for s in ids] == names


def test_a_count_picks_its_form():
    assert [tr("en", "count.visits", n=n) for n in (1, 2)] == ["1 visit", "2 visits"]
    assert [tr("fi", "count.visits", n=n) for n in (1, 3)] == ["1 käynti", "3 käyntiä"]
    assert [tr("sv", "count.visits", n=n) for n in (1, 3)] == ["1 besök", "3 besök"]
    assert [tr("nb", "count.visits", n=n) for n in (1, 3)] == ["1 besøk", "3 besøk"]
    assert [tr("es", "count.visits", n=n) for n in (1, 3)] == ["1 visita", "3 visitas"]


def test_a_missing_word_falls_back_to_english(monkeypatch):
    from app.i18n import fi

    monkeypatch.delitem(fi.MESSAGES, "auth.wrong_password")
    assert tr("fi", "auth.wrong_password") == "Wrong email or password"
    assert tr("de", "auth.wrong_password") == "Wrong email or password"
    assert tr("xx", "species.wild_boar") == "Wild boar"
    with use("fi"):
        assert i18n.t("species.wild_boar") == "Villisika"
        with use("es"):
            assert i18n.t("species.wild_boar") == "Jabalí"
        assert i18n.current() == "fi"
    assert i18n.current() == "en"


@pytest.mark.parametrize(("header", "lang"), [
    (None, "en"), ("", "en"), ("*", "en"), ("fr-FR,fr;q=0.9", "en"),
    ("fi", "fi"), ("fi-FI,fi;q=0.9,en;q=0.8", "fi"), ("sv-SE", "sv"), ("sv-FI", "sv"),
    ("es-419", "es"), ("nb-NO", "nb"), ("no", "nb"), ("nn-NO,nn;q=0.9", "nb"),
    ("de-DE,de;q=0.9,nb;q=0.5", "nb"), ("en-GB,fi;q=0.9", "en"),
    ("fi;q=0.2, sv;q=0.8", "sv"), ("es;q=0, fi;q=0.1", "fi"),
])
def test_the_phones_language_is_read_from_accept_language(header, lang):
    assert from_accept_language(header) == lang


def _sample(key: str) -> dict:
    text = en_catalog.MESSAGES[key]
    forms = text.values() if isinstance(text, dict) else [text]
    names = {name for form in forms for name in _fields(form)}
    return {name: (3 if name == "n" else f"«{name}-7»") for name in names}


@pytest.mark.parametrize("lang", LANGUAGES)
def test_what_is_kept_in_english_is_read_in_each_language(lang):
    for key in en_catalog.STORED:
        params = _sample(key)
        kept = stored(key, **params)
        assert kept == tr("en", key, **params)
        assert localize(kept, lang) == tr(lang, key, **params), key
    # A stored problem inside another (a fetch summary naming the first camera's
    # problem): both are read in the reader's language.
    outer = stored("sync.some_failed", n=2, total=5, error=stored("login.unreadable"))
    assert outer == "2 of 5 cameras failed. The saved password can't be read. Re-enter it."
    assert localize(outer, lang) == tr(lang, "sync.some_failed", n=2, total=5,
                                       error=tr(lang, "login.unreadable"))
    # Words that are no message of ours (a provider's own) stay as they are.
    assert localize("HTTP 502 from api.example", lang) == "HTTP 502 from api.example"
    assert localize(None, lang) is None


@pytest.mark.parametrize("lang", [x for x in LANGUAGES if x != "en"])
def test_every_kept_message_inside_another_is_read_whole_in_each_language(lang):
    """A partial fetch said "1 of 2 cameras failed. SPYPOINT isn't answering properly
    right now." in English inside a Spanish sentence: "{text}. It tries again on the
    next fetch." took the outer message's tail (final review E2E-2)."""
    holders = [k for k in en_catalog.STORED if {"error", "text"} & _sample(k).keys()]
    words = {"SPYPOINT", "UBox", "«provider-7»"}  # a name stays a name
    for inner_key in en_catalog.STORED:
        inner = stored(inner_key, **_sample(inner_key))
        for outer_key in holders:
            slot = "error" if "error" in _sample(outer_key) else "text"
            params = {**_sample(outer_key), slot: inner}
            got = localize(stored(outer_key, **params), lang)
            if outer_key == "sync.some_failed":  # what a partial fetch keeps
                assert got == tr(lang, outer_key, **{**params, slot: localize(inner, lang)}), (
                    outer_key, inner_key)
            english = tr("en", inner_key, **_sample(inner_key))
            # Never a sentence of the inner one left in English.
            for sentence in re.split(r"(?<=[.!?]) ", english):
                if sentence not in words and len(sentence) > 12 and "«" not in sentence:
                    assert sentence not in got, (outer_key, inner_key, sentence)


# ── against the server ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_throttle():
    throttle_mod.throttle.reset()
    yield
    throttle_mod.throttle.reset()


@pytest.fixture
def client(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def estate(db_session):
    e = Estate(name="Piedras Lisas", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db_session.add(e)
    db_session.commit()
    return e


_HASH: list[str] = []


def _user(db, estate, role="member", language="en", email=None, alerts=None, **pref):
    if not _HASH:
        _HASH.append(hash_password(PASSWORD))
    u = User(estate_id=estate.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@estate.local",
             password_hash=_HASH[0], role=role, language=language)
    db.add(u)
    db.flush()
    if alerts is not None:
        db.add(NotificationPref(user_id=u.id, enabled=True, species_ids=alerts, **pref))
    db.commit()
    return u


def _h(user, **extra) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}", **extra}


@requires_db
def test_before_sign_in_the_phones_language_is_used(client, db_session, estate):
    u = _user(db_session, estate, email="pedro@estate.local", language="fi")
    me = "/api/auth/me"
    # English stays exactly as it was.
    assert client.get(me).json()["detail"] == "Not authenticated"
    r = client.get(me, headers={"Authorization": "Bearer junk"})
    assert (r.status_code, r.json()["detail"]) == (401, "Invalid or expired token")
    # Nobody is signed in yet: the phone's language.
    r = client.get(me, headers={"Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8"})
    assert (r.status_code, r.json()["detail"]) == (403, "Et ole kirjautunut sisään")
    r = client.get(me, headers={"Authorization": "Bearer junk", "Accept-Language": "sv-SE"})
    assert (r.status_code, r.json()["detail"]) == (401, "Ogiltig eller utgången inloggning")
    r = client.get(me, headers={"Authorization": "Basic x", "Accept-Language": "es-ES"})
    assert r.json()["detail"] == "Credenciales de acceso no válidas"

    login = "/api/auth/login"
    wrong = {"email": u.email, "password": "not-the-password"}
    r = client.post(login, json=wrong)
    assert (r.status_code, r.json()["detail"]) == (401, "Wrong email or password")
    r = client.post(login, json=wrong, headers={"Accept-Language": "nb-NO"})
    assert r.json()["detail"] == "Feil e-post eller passord"
    r = client.post(login, json=wrong, headers={"Accept-Language": "de-DE, es;q=0.5"})
    assert r.json()["detail"] == "Correo o contraseña incorrectos"


@requires_db
@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_anyone_signed_in_sees_and_sets_their_language(client, db_session, estate, role):
    u = _user(db_session, estate, role)
    assert client.get("/api/auth/me", headers=_h(u)).json()["language"] == "en"

    r = client.patch("/api/auth/me", headers=_h(u), json={"language": "sv"})
    assert r.status_code == 200 and r.json()["language"] == "sv"
    assert client.get("/api/auth/me", headers=_h(u)).json()["language"] == "sv"
    db_session.refresh(u)
    assert u.language == "sv"

    assert client.patch("/api/auth/me", headers=_h(u), json={"language": " FI "}).json()[
        "language"] == "fi"
    # Not one of ours: refused, in the language they read now.
    r = client.patch("/api/auth/me", headers=_h(u), json={"language": "de"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Valitse English, Suomi, Svenska, Norsk tai Español."
    assert client.patch("/api/auth/me", headers=_h(u), json={}).json()["language"] == "fi"
    db_session.refresh(u)
    assert u.language == "fi"
    assert client.patch("/api/auth/me", json={"language": "es"}).status_code == 403


@requires_db
def test_the_persons_own_language_beats_the_phones(client, db_session, estate):
    u = _user(db_session, estate, "member", language="sv")
    r = client.get("/api/users", headers=_h(u, **{"Accept-Language": "es-ES"}))
    assert (r.status_code, r.json()["detail"]) == (403, "Bara jaktmarkens admin kan göra det.")
    u.language = "en"
    db_session.commit()
    r = client.get("/api/users", headers=_h(u, **{"Accept-Language": "es-ES"}))
    assert r.json()["detail"] == "Only the estate admin can do that."


@requires_db
def test_an_admin_can_add_a_person_in_their_language(client, db_session, estate):
    admin = _user(db_session, estate, "admin")
    body = {"email": "Ola@estate.local", "password": PASSWORD, "role": "member"}
    r = client.post("/api/users", headers=_h(admin), json={**body, "language": "nb"})
    assert r.status_code == 200 and r.json()["language"] == "nb"
    ola = db_session.get(User, uuid.UUID(r.json()["id"]))
    assert ola.language == "nb"
    assert client.get("/api/auth/me", headers=_h(ola)).json()["language"] == "nb"
    listed = {x["email"]: x["language"] for x in
              client.get("/api/users", headers=_h(admin)).json()}
    assert listed["ola@estate.local"] == "nb" and listed[admin.email] == "en"

    r = client.post("/api/users", headers=_h(admin),
                    json={**body, "email": "eva@estate.local", "language": "xx"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Pick English, Suomi, Svenska, Norsk or Español."
    r = client.post("/api/users", headers=_h(admin), json={**body, "email": "eva@estate.local"})
    assert r.json()["language"] == "en"
    # The new person signs in and reads the app in theirs.
    r = client.post("/api/auth/login", json={"email": "ola@estate.local", "password": "bad-one!"},
                    headers={"Accept-Language": "nb"})
    assert r.json()["detail"] == "Feil e-post eller passord"


# One place, read in each language: Tonight, a stand's wind, a camera's health, the
# animals, a refusal. English is word for word what it said before round 8.
EXPECTED = {
    "en": {"reason": "No sightings yet.", "health": "Sends photos only, no check-ins",
           "wind": "Wind S 15 km/h — your scent runs N into Umbria, 300 m away.",
           "boar": "Wild boar", "self": "You can't remove yourself"},
    "fi": {"reason": "Ei vielä havaintoja.", "health": "Lähettää vain kuvia, ei tilaraportteja",
           "wind": "Tuuli E 15 km/h — hajusi kulkee suuntaan P makuupaikalle Umbria, "
                   "300 m päähän.",
           "boar": "Villisika", "self": "Et voi poistaa itseäsi"},
    "sv": {"boar": "Vildsvin", "self": "Du kan inte ta bort dig själv"},
    "nb": {"boar": "Villsvin", "self": "Du kan ikke fjerne deg selv"},
    "es": {"boar": "Jabalí", "self": "No puedes quitarte a ti mismo"},
}


@pytest.fixture
def place(db_session, estate, monkeypatch):
    from app.forecasting import model as model_mod

    from .test_weather_and_wind import LAT0, LON0, _cond, _off, _poly

    cam = Camera(estate_id=estate.id, name="PL19", active=True, lat=LAT0, lon=LON0,
                 last_report_at=datetime.now(UTC))
    stand = Stand(estate_id=estate.id, name="Puente", lat=_off(40, 0)[0], lon=_off(40, 0)[1])
    db_session.add_all([cam, stand, Species(id="wild_boar", common_name="Wild boar",
                                            is_priority=True)])
    db_session.add(Zone(estate_id=estate.id, kind="bedding", name="Umbria",
                        polygon=_poly((-200, 300), (300, 300), (300, 500), (-200, 500))))
    db_session.commit()
    monkeypatch.setattr(model_mod, "_tonight_conditions", lambda now: _cond(180.0, 15.0))
    return {"camera": cam, "stand": stand}


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_app_reads_in_each_language(client, db_session, estate, place, lang):
    admin = _user(db_session, estate, "admin", language=lang)
    h = _h(admin, **{"Accept-Language": "en"})  # the person's, not the phone's
    want = EXPECTED[lang]

    tonight = client.get("/api/forecast/tonight", headers=h).json()
    assert tonight["verdict"] == "NO_DATA"  # codes stay codes
    assert tonight["reason"] == want.get("reason", tr(lang, "tonight.none.yet"))

    wind = client.get(f"/api/stands/{place['stand'].id}/wind", headers=h).json()
    assert wind["status"] == "scent_carries"
    if "wind" in want:
        assert wind["text"] == want["wind"]
    else:
        assert "Umbria" in wind["text"] and "300 m" in wind["text"]
        assert wind["text"] != EXPECTED["en"]["wind"] and "scent" not in wind["text"]

    (cam,) = client.get("/api/cameras", headers=h).json()
    assert cam["health"]["status"] == "ok"
    assert cam["health"]["detail"] == want.get("health", tr(lang, "health.photos_only"))

    boar = next(s for s in client.get("/api/species", headers=h).json() if s["id"] == "wild_boar")
    assert (boar["common_name"], boar["default_name"], boar["custom"]) == (
        want["boar"], want["boar"], False)

    r = client.delete(f"/api/users/{admin.id}", headers=h)
    assert (r.status_code, r.json()["detail"]) == (400, want["self"])
    r = client.delete(f"/api/stands/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == tr(lang, "stands.gone")


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_photos_by_animal_on_tonights_fold_are_named_in_the_language(
    client, db_session, estate, place, lang,
):
    """Tonight's "Photos by animal" said "Wild Boar" in every language: the one list
    still printing the stored name."""
    db_session.get(Species, "wild_boar").common_name = "Wild Boar"  # an older build's
    now = datetime.now(UTC)
    for n in range(3):
        img = Image(camera_id=place["camera"].id, captured_at=now - timedelta(hours=n + 1),
                    processed_at=now, is_empty_frame=False, reviewed=False,
                    original_path=f"/nonexistent/{n}.jpg", person_conf=0.0, vehicle_conf=0.0)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id="wild_boar", group_size=1))
    db_session.commit()
    user = _user(db_session, estate, "viewer", language=lang)
    got = client.get("/api/analytics/overview", headers=_h(user)).json()
    assert got["by_species"] == [
        {"species": EXPECTED[lang]["boar"], "species_id": "wild_boar", "count": 3}]


@requires_db
def test_the_admins_own_name_for_an_animal_is_used_in_every_language(
    client, db_session, estate, place,
):
    admin = _user(db_session, estate, "admin", language="en")
    ana = _user(db_session, estate, "admin", language="fi")

    r = client.patch("/api/species/wild_boar", headers=_h(admin), json={"common_name": "Big pig"})
    assert r.json()["common_name"] == "Big pig" and r.json()["custom"] is True
    for who in (admin, ana):
        boar = next(s for s in client.get("/api/species", headers=_h(who)).json()
                    if s["id"] == "wild_boar")
        assert (boar["common_name"], boar["custom"]) == ("Big pig", True)
    assert next(s for s in client.get("/api/species", headers=_h(ana)).json()
                if s["id"] == "wild_boar")["default_name"] == "Villisika"
    for lang in LANGUAGES:
        assert i18n.species_name("wild_boar", "Big pig", lang) == "Big pig"

    # Ana, the other admin, saves the name the app shows her: the app's own, no rename.
    r = client.patch("/api/species/wild_boar", headers=_h(ana), json={"common_name": "villisika"})
    assert (r.json()["common_name"], r.json()["custom"]) == ("Villisika", False)
    db_session.refresh(db_session.get(Species, "wild_boar"))
    assert db_session.get(Species, "wild_boar").common_name == "Wild boar"
    boar = next(s for s in client.get("/api/species", headers=_h(admin)).json()
                if s["id"] == "wild_boar")
    assert (boar["common_name"], boar["custom"]) == ("Wild boar", False)


@requires_db
def test_a_login_problem_kept_in_english_is_read_in_the_admins_language(
    client, db_session, estate,
):
    admin = _user(db_session, estate, "admin", language="es")
    account = CameraAccount(estate_id=estate.id, username="marco@example.com",
                            provider="spypoint", label="Marco",
                            password_enc=crypto.encrypt("guest-secret"))
    db_session.add(account)
    db_session.flush()
    logins.record(db_session, account, error=logins.UNREADABLE)
    db_session.commit()
    assert account.last_error == "The saved password can't be read. Re-enter it."

    rows = client.get("/api/camera-accounts", headers=_h(admin)).json()
    row = next(r for r in rows if r["id"] == str(account.id))
    assert row["status"]["error"] == "No se puede leer la contraseña guardada. Vuelve a escribirla."
    assert row["status"]["password_problem"] is True  # judged on the English kept
    admin.language = "en"
    db_session.commit()
    rows = client.get("/api/camera-accounts", headers=_h(admin)).json()
    row = next(r for r in rows if r["id"] == str(account.id))
    assert row["status"]["error"] == "The saved password can't be read. Re-enter it."


# ── pushes: in the language of the person they go to ────────────────────────


class _Recorder:
    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, db, user_id, payload, quiet=False):
        self.calls.append((user_id, payload))
        return {"sent": 1, "failed": 0, "removed": 0, "subscriptions": 1}

    def to(self, user) -> list[dict]:
        return [p for u, p in self.calls if u == user.id]


@pytest.fixture
def rec(db_session, monkeypatch):
    from app.core import db as core_db

    r = _Recorder()
    monkeypatch.setattr(push, "send_to_user", r)
    monkeypatch.setattr(core_db, "SessionLocal", core_db.server_sessions(db_session.get_bind()))
    return r


def _team(db, estate, **pref) -> dict:
    db.add_all([Species(id="wild_boar", common_name="Wild boar", is_priority=True),
                Species(id="red_deer", common_name="Red deer", is_priority=True)])
    db.commit()
    return {lang: _user(db, estate, "member", language=lang, email=f"{lang}@estate.local",
                        alerts=["wild_boar", "red_deer"], **pref) for lang in LANGUAGES}


def _frame(db, cam, species_id, at):
    img = Image(camera_id=cam.id, captured_at=at, original_path="x.jpg")
    db.add(img)
    db.flush()
    db.add(Detection(image_id=img.id, species_id=species_id, species_conf=0.9,
                     created_at=at + timedelta(minutes=1)))
    db.commit()
    return img


@requires_db
def test_a_sighting_is_told_to_each_person_in_their_language(db_session, estate, rec):
    team = _team(db_session, estate)
    cam = Camera(estate_id=estate.id, name="PL19")
    db_session.add(cam)
    db_session.commit()
    t0 = datetime.now(UTC)
    dispatch.dispatch_new_sightings(db_session, now=t0)
    t1 = t0 + timedelta(minutes=15)
    img = _frame(db_session, cam, "wild_boar", t1 - timedelta(minutes=3))
    clock = img.captured_at.astimezone(MADRID).strftime("%H:%M")

    assert dispatch.dispatch_new_sightings(db_session, now=t1)["notifications"] == 5
    said = {lang: (p["title"], p["body"]) for lang, u in team.items() for p in rec.to(u)}
    assert said == {
        "en": ("Wild boar at PL19", f"1 visit at {clock}."),
        "fi": ("Villisika, kamera PL19", f"1 käynti klo {clock.replace(':', '.')}."),
        "sv": ("Vildsvin vid PL19", f"1 besök kl. {clock}."),
        "nb": ("Villsvin ved PL19", f"1 besøk kl. {clock}."),
        "es": ("Jabalí en PL19", f"1 visita a las {clock}."),
    }
    # The in-app record reads the same as the push.
    for lang, u in team.items():
        n = db_session.query(Notification).filter_by(user_id=u.id).one()
        assert (n.title, n.body) == said[lang]
        assert n.species_id == "wild_boar"

    # An admin's own name for the animal goes out in every language.
    db_session.get(Species, "wild_boar").common_name = "Big pig"
    db_session.commit()
    rec.calls.clear()
    t2 = t1 + timedelta(hours=3)
    _frame(db_session, cam, "wild_boar", t2 - timedelta(minutes=3))
    dispatch.dispatch_new_sightings(db_session, now=t2)
    titles = {lang: p["title"] for lang, u in team.items() for p in rec.to(u)}
    assert titles["fi"] == "Big pig, kamera PL19" and titles["en"] == "Big pig at PL19"
    assert titles["es"] == "Big pig en PL19"


@requires_db
def test_tonights_plan_is_sent_in_each_persons_language(db_session, estate, rec, monkeypatch):
    from .test_alert_rhythm import _claim

    night = date(2026, 9, 27)
    sunset = plan.sunset_of(night)
    team = _team(db_session, estate, plan_push=True)
    cams = {n: Camera(estate_id=estate.id, name=n) for n in ("PL19", "Charca")}
    db_session.add_all(cams.values())
    db_session.commit()
    _claim(db_session, cams, night)
    monkeypatch.setattr(plan, "_wind", lambda db, p, now: {"status": "clean"})

    out = plan.send_daily_plan(db_session, now=sunset - timedelta(hours=1, minutes=55))
    assert out["status"] == "done" and out["people"] == 5
    local = sunset.astimezone(MADRID).strftime("%H:%M")
    said = {lang: (p["title"], p["body"]) for lang, u in team.items() for p in rec.to(u)}
    assert said["en"] == (f"▲ Charca · wind right · sunset {local}",
                          "Best odds. Wild boar, best 20:40 to 22:10.")
    assert said["sv"][0] == f"▲ Charca · rätt vind · solnedgång {local}"
    assert said["sv"][1].startswith("Bäst chans. Vildsvin, bäst 20:40–22:10")
    assert said["es"][0] == f"▲ Charca · viento bueno · puesta de sol {local}"
    assert "Jabalí, mejor de 20:40 a 22:10." in said["es"][1]
    # Finnish writes the clock with a dot, as the app's own times do there.
    assert said["fi"][0] == f"▲ Charca · tuuli sopiva · auringonlasku {local.replace(':', '.')}"
    assert "Villisika" in said["fi"][1] and "Villsvin" in said["nb"][1]


@requires_db
def test_what_waited_through_quiet_hours_is_told_in_the_persons_language(
    db_session, estate, rec,
):
    team = _team(db_session, estate, quiet_start=time(0, 0), quiet_end=time(7, 0))
    cam = Camera(estate_id=estate.id, name="PL19")
    db_session.add(cam)
    db_session.commit()
    night = datetime(2026, 9, 15, 22, 55, tzinfo=UTC)  # 00:55 in Madrid
    dispatch.dispatch_new_sightings(db_session, now=night - timedelta(minutes=30))
    _frame(db_session, cam, "wild_boar", night - timedelta(minutes=2))
    dispatch.dispatch_new_sightings(db_session, now=night)
    assert rec.calls == []

    out = hold.deliver_held(db_session, now=night + timedelta(hours=6, minutes=10))
    assert out["summaries"] == 5
    said = {lang: (p["title"], p["body"]) for lang, u in team.items() for p in rec.to(u)}
    assert said["en"] == ("During your quiet hours",
                          "Wild boar: 1 visit at PL19, last one 00:53 last night.")
    assert said["fi"][0] == "Hiljaisten tuntiesi aikana"
    assert said["fi"][1].startswith("Villisika: 1 käynti (PL19)")
    assert said["sv"][0] == "Under dina tysta timmar"
    assert said["sv"][1].startswith("Vildsvin: 1 besök vid PL19, senast ")
    assert said["nb"][0] == "I de stille timene dine"
    assert said["es"][0] == "Durante tus horas de silencio"
    assert said["es"][1].startswith("Jabalí: 1 visita en PL19, la última ")


@requires_db
def test_a_team_note_reaches_each_teammate_in_their_language(client, db_session, estate, rec):
    pedro = _user(db_session, estate, "member", language="en", email="pedro.garcia@x.es")
    team = {lang: _user(db_session, estate, "member", language=lang, email=f"{lang}@x.es",
                        alerts=["wild_boar"]) for lang in ("en", "fi", "es")}
    cam = Camera(estate_id=estate.id, name="Charca")
    db_session.add_all([cam, Species(id="wild_boar", common_name="Wild boar", is_priority=True)])
    db_session.flush()
    img = Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path="p.jpg",
                is_empty_frame=False, processed_at=datetime.now(UTC))
    db_session.add(img)
    db_session.flush()
    db_session.add(Detection(image_id=img.id, species_id="wild_boar", species_conf=0.9))
    db_session.commit()

    r = client.post(f"/api/images/{img.id}/notes", headers=_h(pedro),
                    json={"text": "Big boar, third night running", "tell_team": True})
    assert r.status_code == 201 and r.json()["told"] == 3
    said = {lang: (p["title"], p["body"]) for lang, u in team.items() for p in rec.to(u)}
    assert said == {
        "en": ("Worth a look: Wild boar at Charca", "Pedro: Big boar, third night running"),
        "fi": ("Kannattaa katsoa: Villisika, kamera Charca",
               "Pedro: Big boar, third night running"),
        "es": ("Merece la pena: Jabalí en Charca", "Pedro: Big boar, third night running"),
    }
    other = Image(camera_id=cam.id, captured_at=datetime.now(UTC), original_path="q.jpg",
                  is_empty_frame=False, processed_at=datetime.now(UTC))
    db_session.add(other)
    db_session.flush()
    db_session.add(Detection(image_id=other.id, species_id="wild_boar", species_conf=0.9))
    db_session.commit()
    rec.calls.clear()
    client.post(f"/api/images/{other.id}/notes", headers=_h(pedro),
                json={"text": None, "tell_team": True})
    bodies = {lang: p["body"] for lang, u in team.items() for p in rec.to(u)}
    assert bodies == {"en": "Pedro marked a photo", "fi": "Pedro merkitsi kuvan",
                      "es": "Pedro ha marcado una foto"}


# ── a class the app sends back (R8BE-1) ──────────────────────────────────────


@pytest.fixture
def herd(db_session, estate):
    """One photo each of a stag, a red deer nobody could sex, an otter and a coypu:
    "Hjort" is the stag in Swedish and the red deer in Norwegian, "Nutria" the otter
    in Spanish and the coypu in English."""
    cam = Camera(estate_id=estate.id, name="PL19", active=True, lat=39.09, lon=-1.36,
                 last_report_at=datetime.now(UTC))
    db_session.add_all([cam, Species(id="red_deer", common_name="Red deer", is_priority=True),
                        Species(id="otter", common_name="Otter"),
                        Species(id="nutria", common_name="Nutria")])
    db_session.commit()
    # Last night from 21:00, an hour apart: the Insights count nights (18:00-06:00).
    from app.forecasting.exposure import current_night

    at = datetime.combine(current_night() - timedelta(days=1), time(21),
                          tzinfo=ZoneInfo("Europe/Madrid"))
    out = {}
    for name, sid, sex in (("stag", "red_deer", "male"), ("deer", "red_deer", "unknown"),
                           ("otter", "otter", "unknown"), ("coypu", "nutria", "unknown")):
        img = Image(camera_id=cam.id, captured_at=at, original_path=f"{name}.jpg",
                    processed_at=at, is_empty_frame=False, reviewed=True)
        db_session.add(img)
        db_session.flush()
        db_session.add(Detection(image_id=img.id, species_id=sid, species_conf=0.9, sex=sex,
                                 created_at=at))
        out[name] = str(img.id)
        at += timedelta(hours=1)  # a visit each
    db_session.commit()
    return out


def _ids(r) -> list[str]:
    assert r.status_code == 200, r.text
    return sorted(i["image_id"] for i in r.json()["items"])


@requires_db
@pytest.mark.parametrize("lang, word, means", [
    ("sv", "Hjort", "stag"),  # a stag
    ("nb", "Hjort", "deer"),  # a red deer nobody could sex
    ("en", "Stag", "stag"),
    ("nb", "Stag", "stag"),   # an older link, in English
    ("fi", "Saksanhirvi", "deer"),
])
def test_a_class_tapped_is_read_in_the_readers_own_language(
    client, db_session, estate, herd, lang, word, means,
):
    u = _user(db_session, estate, "member", language=lang)
    got = _ids(client.get("/api/species/red_deer/photos", params={"label": word},
                          headers=_h(u)))
    assert got == [herd[means]]
    got = _ids(client.get("/api/insights/class", params={"label": word}, headers=_h(u)))
    assert got == [herd[means]]


@requires_db
@pytest.mark.parametrize("lang, means", [("es", "otter"), ("en", "coypu"), ("fi", "coypu")])
def test_nutria_is_the_otter_in_spanish_and_the_coypu_in_english(
    client, db_session, estate, herd, lang, means,
):
    u = _user(db_session, estate, "member", language=lang)
    got = _ids(client.get("/api/insights/class", params={"label": "Nutria"}, headers=_h(u)))
    assert got == [herd[means]]


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_class_comes_with_a_key_the_same_in_every_language(
    client, db_session, estate, herd, lang,
):
    u = _user(db_session, estate, "member", language=lang)
    h = _h(u)
    deer = next(s for s in client.get("/api/species/spotted", headers=h).json()
                if s["id"] == "red_deer")
    keys = {c["label"]: c["key"] for c in deer["classes"]}
    assert sorted(keys.values()) == ["red_deer", "red_deer.stag"]
    assert keys[tr(lang, "class.stag")] == "red_deer.stag"
    assert keys[tr(lang, "species.red_deer")] == "red_deer"
    # The gallery and the Insights makeup are asked by key, in any language.
    items = client.get("/api/species/red_deer/photos", params={"key": "red_deer.stag"},
                       headers=h).json()["items"]
    assert [(i["image_id"], i["class_key"], i["label"]) for i in items] == [
        (herd["stag"], "red_deer.stag", tr(lang, "class.stag"))]
    assert _ids(client.get("/api/species/red_deer/photos", params={"key": "red_deer"},
                           headers=h)) == [herd["deer"]]
    makeup = {x["key"]: x["label"]
              for x in client.get("/api/insights", headers=h).json()["composition"]}
    assert makeup == {"red_deer.stag": tr(lang, "class.stag"),
                      "red_deer": tr(lang, "species.red_deer"),
                      "otter": tr(lang, "species.otter"), "nutria": tr(lang, "species.nutria")}
    for key, name in (("red_deer.stag", "stag"), ("red_deer", "deer"), ("otter", "otter"),
                      ("nutria", "coypu")):
        assert _ids(client.get("/api/insights/class", params={"key": key}, headers=h)) == [
            herd[name]]
    # A chip that is two classes carries both; a key for another animal is nothing.
    assert _ids(client.get("/api/insights/class", params={"key": "red_deer,red_deer.stag"},
                           headers=h)) == sorted([herd["stag"], herd["deer"]])
    assert _ids(client.get("/api/species/red_deer/photos", params={"key": "otter"},
                           headers=h)) == []
    assert _ids(client.get("/api/insights/class", params={"key": "red_deer.piglet"},
                           headers=h)) == []
    r = client.get("/api/insights/class", headers=h)
    assert (r.status_code, r.json()["detail"]) == (422, tr(lang, "insights.class_missing"))


# ── refusals the app acts on (R8BE-2) ────────────────────────────────────────


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_a_refusal_the_app_acts_on_has_a_code_beside_its_words(
    client, db_session, estate, lang,
):
    """The words are in the reader's language, so the app knows a refusal by its
    code: "Save again to keep it as an animal photo" on empty_frame, sign in again
    on signed_out. `detail` stays the words, for an app that only shows them."""
    cam = Camera(estate_id=estate.id, name="PL19")
    db_session.add_all([cam, Species(id="lagomorph", common_name="Rabbit", hidden=True)])
    db_session.flush()
    at = datetime.now(UTC) - timedelta(hours=3)

    def photo(species=(), **kw):
        img = Image(camera_id=cam.id, captured_at=at, original_path=f"{uuid.uuid4()}.jpg",
                    **{"processed_at": at, "is_empty_frame": False, **kw})
        db_session.add(img)
        db_session.flush()
        for sid in species:
            db_session.add(Detection(image_id=img.id, species_id=sid, species_conf=0.9))
        return img

    empty = photo(is_empty_frame=True)
    rabbit = photo(species=("lagomorph",))
    walker = photo(person_conf=0.9)
    unseen = photo(processed_at=None, is_empty_frame=None, reviewed=False)
    db_session.commit()
    admin = _user(db_session, estate, "admin", language=lang)
    member = _user(db_session, estate, "member", language=lang)

    for who, img, code, key in (
        (member, empty, "empty_frame", "notes.empty_frame"),
        (member, rabbit, "hidden_only", "notes.hidden_only"),
        (admin, walker, "people_only", "notes.people_only"),
        (admin, unseen, "not_looked", "notes.not_looked"),
    ):
        r = client.post(f"/api/images/{img.id}/notes", headers=_h(who), json={"text": "boar"})
        assert (r.status_code, r.json()) == (409, {"detail": tr(lang, key), "code": code})

    # A sign-in that no longer works (a new password elsewhere, a removed person, an
    # expired token): nobody is signed in, so the phone's language; the same code.
    member.token_version = (member.token_version or 0) + 1
    db_session.commit()
    r = client.get("/api/auth/me", headers=_h(member, **{"Accept-Language": lang}))
    assert (r.status_code, r.json()) == (401, {"detail": tr(lang, "auth.signed_out"),
                                               "code": "signed_out"})
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer junk",
                                            "Accept-Language": lang})
    assert (r.status_code, r.json()) == (401, {"detail": tr(lang, "auth.token_invalid"),
                                               "code": "signed_out"})
    # Any other refusal is words alone, as before.
    r = client.delete(f"/api/stands/{uuid.uuid4()}", headers=_h(admin))
    assert r.json() == {"detail": tr(lang, "stands.gone")}


# ── numbers in each language's decimal mark (R8BE-3) ─────────────────────────


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_slope_winds_numbers_use_the_languages_decimal_mark(db_session, place, lang):
    import re

    from app.forecasting import bedding, conditions

    from .test_weather_and_wind import _slope_north

    _slope_north(db_session)
    evening = conditions.sunset_of(date(2026, 9, 26)) + timedelta(minutes=45)
    stand = place["stand"]
    with use(lang):
        report = bedding.stand_wind_report(
            db_session, stand_name=stand.name, lat=stand.lat, lon=stand.lon,
            wind_dir_deg=90.0, wind_speed_kmh=3.0, when=evening)
    assert report["source"] == "katabatic"
    speed = f"{report['speed_kmh']:.1f}"
    pct = f"{report['slope']['slope_pct']:.1f}"
    mark = tr(lang, "num.decimal_mark")
    text = report["text"]
    for number in (speed, pct):
        assert number.replace(".", mark) in text, text
    if lang == "en":  # word for word as before
        assert f"~{speed} km/h ({pct}% fall)" in text
    else:
        assert not re.search(r"\d\.\d", text), text


@pytest.mark.parametrize("lang", LANGUAGES)
def test_a_number_kept_in_english_is_read_in_the_languages_mark(lang):
    kept = stored("fetch.disk_full", gb="12.3")
    mark = tr(lang, "num.decimal_mark")
    assert localize(kept, lang) == tr(lang, "fetch.disk_full", gb=f"12{mark}3")


# ── the moon (R8BE-4) ────────────────────────────────────────────────────────


@requires_db
@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_moon_is_said_in_the_readers_language_with_a_key_beside_it(
    client, db_session, estate, lang,
):
    from app.enrichment.astro import MOON_PHASES

    keys = {p.lower().replace(" ", "_") for p in MOON_PHASES}
    u = _user(db_session, estate, "member", language=lang)
    tonight = client.get("/api/analytics/overview", headers=_h(u)).json()["tonight"]
    days = client.get("/api/insights", headers=_h(u)).json()["outlook"]
    for said in (tonight, *days):
        assert said["moon_phase_key"] in keys
        assert said["moon_phase"] == tr(lang, f"moon.{said['moon_phase_key']}")


# ── animals' names inside a push's list (R8BE-5) ─────────────────────────────


@pytest.mark.parametrize("lang, body", [
    ("en", "Wild boar, Red deer and Big tusker, last one 22:14."),
    ("fi", "Villisika, saksanhirvi ja Big tusker, viimeisin klo 22.14."),
    ("sv", "Vildsvin, kronhjort och Big tusker, senast {t}."),
    ("nb", "Villsvin, hjort og Big tusker, sist {t}."),
    ("es", "Jabalí, ciervo y Big tusker, el último {t}."),
])
def test_a_list_of_animals_starts_with_a_capital_and_goes_on_in_lower_case(lang, body):
    """The first name starts the sentence; the others are words inside it, lower case
    in the languages that write them so. An admin's own name stays as they wrote it."""
    t0 = datetime(2026, 9, 20, 22, 14, tzinfo=MADRID)
    ds = []
    for i, (sid, name) in enumerate([("wild_boar", "Wild boar"), ("red_deer", "Red deer"),
                                     ("roe_deer", "Big tusker")]):
        d = dispatch.SpeciesDigest(sid, name)
        for k in range(3 - i):
            d.add(uuid.uuid4(), t0 - timedelta(hours=k), "PL19")
        ds.append(d)
    with use(lang):
        _, said = dispatch.compose_summary(ds, MADRID)
        when = tr(lang, "push.time", time="22:14")
    assert said == body.replace("{t}", when)


@pytest.mark.parametrize("lang, verdict", [("en", "Not enough to say"),
                                           ("es", "Sin datos suficientes")])
def test_the_no_data_verdict_reads_naturally(lang, verdict):
    assert tr(lang, "verdict.no_data") == verdict


@pytest.mark.parametrize(("lang", "want"), [
    ("en", "21:40"), ("fi", "21.40"), ("sv", "21:40"), ("nb", "21:40"), ("es", "21:40")])
def test_a_time_the_server_writes_follows_the_languages_clock(lang, want):
    """Finnish showed "05.18" (the app's own times) beside "Auringonnousu 07:58" (the
    server's): one clock style per language (final review FUX-2)."""
    from app.i18n import clock

    assert clock(time(21, 40), lang) == want
    assert clock(datetime(2026, 9, 27, 21, 40), lang) == want
    assert clock("21:40", lang) == want
    assert clock(21, lang) == want.replace("40", "00")


def test_a_camera_quiet_for_days_says_the_day_not_hours():
    """"No check-in for 80h" on Tonight, "Quiet since Thursday night" on Cameras: one
    phrase, the day it last checked in (final review FUX-9)."""
    from types import SimpleNamespace

    from app.health import camera_health

    now = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)  # a Monday
    cam = SimpleNamespace(
        last_report_at=now - timedelta(hours=80), spypoint_id="sp", ubox_uid=None,
        photo_limit=None, photo_count=None, battery_pct=80, fetch_error=None,
        retired_at=None, active=True)
    with use("en"):
        got = camera_health(cam, now)
    assert got["status"] == "offline" and got["detail"] == "No check-in since Friday"
    cam.last_report_at = now - timedelta(days=12)
    with use("es"):
        assert camera_health(cam, now)["detail"] == "Sin conectar desde el 16 sept"
    cam.last_report_at, cam.photo_count, cam.photo_limit = now, 1000, 1000
    with use("en"):
        assert camera_health(cam, now)["detail"] == "Out of photo credits (1000/1000)"
