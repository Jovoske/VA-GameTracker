# Languages — what the server says, in five languages

English (the default), Finnish, Swedish, Norwegian bokmål and Spanish: `en`, `fi`,
`sv`, `nb`, `es`. English reads exactly as it did before languages came in.

## Which language an answer is in

1. The signed-in person's own: `users.language` (migration 0033, `'en'` for everyone
   already there). They set it with `PATCH /api/auth/me {"language": "fi"}`, any
   role; `GET /api/auth/me` returns it. An admin can set it when adding a person
   (`POST /api/users {..., "language": "sv"}`).
2. Before sign-in (the sign-in page, a refused or expired sign-in): the
   `Accept-Language` the app sends, by its weights. `no` and `nn` read as bokmål.
3. Otherwise English.

A push goes out in the language of the person it goes to, whoever's run sends it:
a sighting, Worth a look from a teammate, the summary after quiet hours or a sit,
and tonight's plan.

## How it is written

`backend/app/i18n/` holds one catalog per language (`en.py`, `fi.py`, ...), the same
keys and `{placeholders}` in each. Code says

    t("health.battery_low", pct=15)          # in the request's language
    tr("fi", "count.visits", n=3)            # "3 käyntiä"
    with use(person.language): compose(...)  # a push in its recipient's language

A message that depends on a number is `{"one": ..., "other": ...}`, picked by `n`.
A key missing from a catalog is said in English. `tests/test_i18n.py` keeps every
catalog complete, with the same placeholders, and checks the endpoints and pushes in
each language.

Hunters' words used: Swedish vildsvin, kronhjort, rådjur, dovhjort, åtel, pass,
torn; Finnish villisika, saksanhirvi, metsäkauris, kuusipeura, ruokintapaikka,
passi, torni; Norwegian villsvin, hjort, rådyr, dåhjort, foringsplass, post, tårn;
Spanish jabalí, ciervo, corzo, gamo, comedero, puesto, torreta, aguardo.

## Words kept in the database

A login's last problem, a camera's fetch error, a fetch's summary, why the AI pass
stopped, the restore check's problems, the terrain and repeat-animal status: these
are written once by a scheduled run nobody is reading, so they are kept in English
(`stored(key, ...)`, keys listed in `en.STORED`) and read back in the reader's
language (`localize(text)`), which matches the English template and translates it
and its parts. Code that decides on them (is this a password problem?) keeps
comparing the English.

Notifications already sent keep the language they were sent in.

## Animal names

Each species has its name in every catalog (`species.wild_boar`: Wild boar,
Villisika, Vildsvin, Villsvin, Jabalí). An admin's own name for one (Settings) is
used in every language. Saving the name the app itself shows you (in your language
or in English) is no rename: it stays each reader's own. Inside a sentence, or after
the first name of a list, Finnish, Swedish, Norwegian and Spanish write the app's
names in lower case ("Villisika, saksanhirvi ja 2 muuta"; `species_inside`); an
admin's own name is written as they wrote it.

## Classes sent back as filters

A class chip (Stag, Sow + piglets, Red deer) comes with a `key` the same in every
language: `red_deer.stag`, `wild_boar.sow_piglets`, or the species' id for its own
name (`red_deer`). `GET /api/species/spotted` gives each class its `key`, each photo
in `GET /api/species/{id}/photos` its `class_key`, and each class of the Insights
makeup (`GET /api/insights`, `composition`) its `key`; both galleries take it back
as `?key=` (one chip that is two classes carries both, comma-joined). The app should
ask by key: a label is a word in one language, and two languages share words for
different things ("Hjort" is a stag in Swedish and a red deer in Norwegian; "Nutria"
the otter in Spanish and the coypu in English).

A `?label=` is still understood, read in one language at a time: the reader's own,
then English (an older link), then the others; the first that knows the word says
what it means, and two languages are never mixed.

## Refusals the app acts on

The words of a refusal are in the reader's language, so an app cannot tell one from
another by them. A refusal the app branches on carries a `code` beside its words,
the same in every language: `{"detail": "<words>", "code": "empty_frame"}`
(`app/api/refusal.py`). `detail` stays the words, as for every other refusal.

- A note on a photo (`POST /api/images/{id}/notes`, 409): `empty_frame` (marked
  "nothing in it": save again with `keep` to keep it as an animal photo),
  `hidden_only`, `people_only`, `not_looked`.
- A sign-in that no longer works (401: a password changed elsewhere, the person was
  removed, an expired or broken token): `signed_out`.

The moon's phase is said in the reader's words (`moon_phase`) with a key beside it
(`moon_phase_key`: `full_moon`, `waxing_crescent`, ...) on Tonight's conditions, the
Insights outlook and `/api/analytics/overview`.

## Numbers

A decimal is written with the language's mark (`decimal`, `fixed`: "1,5 km/h" in
Finnish, Swedish, Norwegian and Spanish; "1.5 km/h" in English): the slope-wind
speeds and gradients, and the free space a kept "disk full" message names.

## Not translated

Operator tools (`python -m app.manage`, the deploy and backup scripts, logs), the
API's own validation errors for malformed requests (422: "Field required", and the
"Value error, " before our own validators' words), and the screens' own words, which
the app translates itself. Text written once for one reader stays in the language it
was written in: a sit's wind line (`Sit.wind_text`, shown only to the sitter), pushes
already sent, and the stand an admin's run names after its camera ("PL19 stand").
