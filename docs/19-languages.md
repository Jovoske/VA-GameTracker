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
or in English) is no rename: it stays each reader's own. Labels the app sends back
as filters ("Purke + smågriser") are understood in any of the five languages.

## Not translated

Operator tools (`python -m app.manage`, the deploy and backup scripts, logs), the
API's own validation errors for malformed requests (422), and the screens' own
words, which the app translates itself.
