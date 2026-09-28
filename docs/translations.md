# Translations: the app in five languages

GameSense speaks **English** (the default), **Suomi** (Finnish), **Svenska**
(Swedish), **Norsk bokmål** (Norwegian) and **Español** (Spanish). This page is for
whoever fixes a word, checks a translation or adds a language. The server's side in
more depth is in [19-languages.md](19-languages.md).

> **Read this first.** The Finnish, Swedish, Norwegian and Spanish texts were written
> by a machine, with hunters' words chosen on purpose (see "Hunters' words" below),
> but nobody who speaks the language has read them through yet. Before the team
> relies on a language, have **one native-speaking hunter read the whole app once**
> in it (Tonight, a sit, Stands, the map and its sheets, Photos, Cameras, Insights,
> Settings, an alert on the phone) and note anything that reads oddly. Fixing a word
> is a one-line change (below).

## How it works

- **Who reads which language.** Each person picks theirs in Settings → Language
  (or on the sign-in page). It is kept on the phone and saved to the person on the
  server, so every phone they sign in on, and every push they get, speaks it.
  Before sign-in the phone's own language is used; anything else is English.
- **Two sets of words.** The screens' words live in the app
  (`frontend/src/i18n/en.ts`, `fi.ts`, `sv.ts`, `nb.ts`, `es.ts`). What the server
  writes into sentences (the plan's reason, the Changed line, a camera's health, a
  push, a refusal) lives on the server (`backend/app/i18n/en.py`, `fi.py`, `sv.py`,
  `nb.py`, `es.py`). Both are one dictionary per language with the same keys.
- **Dates, times and numbers** are written by the language's own rules (the phone's
  Intl for `en-GB`, `fi-FI`, `sv-SE`, `nb-NO`, `es-ES`): a 24-hour clock in all five,
  "21.40" in Finnish and "21:40" in the rest, "1,5 km/h" with a comma where the
  language uses one. A time the server sends ready-made ("20:30") is put in the same
  style on screen, and the server writes its own sentences' times that way too.
- **Words that change with a count** ("1 visit", "3 visits") have a form per case:
  `{ one: '…', other: '…' }`, picked by the number.
- **Placeholders** such as `{camera}`, `{n}` or `{time}` are filled in by the code.
  Keep them exactly as they are, in any order the sentence needs.
- **Animal names** have a name in every language. An admin's own name for an animal
  (Settings → Animals in the advice) is used in every language.
- **Messages kept in the database** (a login's last problem, a fetch's summary) are
  stored in English and put into the reader's language when shown, so they follow a
  change of language too.

## Fixing a word

1. Find the English text on screen in `frontend/src/i18n/en.ts` (screens) or
   `backend/app/i18n/en.py` (sentences the server writes). Search for a few words of
   it; the key next to it (`'tonight.sunset'`, `"changed.busier"`) is the same in
   every language.
2. Open the language's file (`fi.ts`, `sv.py`, ...) and change the text for that key.
   Keep the `{placeholders}`, and both `one` and `other` forms where there are two.
3. Check it (below) and push. The server picks it up on its next deploy.

English itself is changed the same way. A server sentence that the tests quote word
for word (`backend/tests`) needs its test updated in the same change.

## Checking a change

- Screens: `cd frontend && node tests/i18n-keys.cjs` (every language has every key,
  the same placeholders and count forms, nothing empty), then `npm run build`.
- Server: `cd backend && python -m pytest tests/test_i18n.py` (the same for the
  server's catalogs, and the main screens and pushes read in each language).
- To see it: sign in, Settings → Language, and walk the pages. `frontend/tests/
  languages.cjs` does that at 320 px for all five and fails on text that overflows.

## Adding a language

1. Screens: copy `frontend/src/i18n/en.ts` to `<code>.ts`, translate every value, add
   the language to `LANGS` (its name in itself and its Intl locale) and to `loaders`
   in `frontend/src/i18n/core.ts`, and to `LANGS`/`LOCALES` in
   `frontend/tests/i18n-keys.cjs`.
2. Server: copy `backend/app/i18n/en.py` to `<code>.py`, translate it, and add the
   code to `LANGUAGES` in `backend/app/i18n/__init__.py`. If the language writes the
   clock with a dot, add it to `_CLOCK_DOT` there and to `CLOCK_DOT` in
   `frontend/src/i18n/core.ts`; if it writes animal names in lower case inside a
   sentence, to `_LOWER_INSIDE`.
3. The database accepts only known codes: a small migration adds the code to the
   `ck_users_language_valid` check on `users.language` (as 0033 made it).
4. Run the checks above; `test_i18n.py` and `i18n-keys.cjs` list what is missing.

## Hunters' words

Chosen on purpose, and worth keeping when a sentence is reworded:

- Swedish: vildsvin, kronhjort, rådjur, dovhjort, åtel, pass, torn.
- Finnish: villisika, saksanhirvi, metsäkauris, kuusipeura, ruokintapaikka, passi,
  torni.
- Norwegian: villsvin, hjort, rådyr, dåhjort, foringsplass, post, tårn.
- Spanish: jabalí, ciervo, corzo, gamo, comedero, puesto, torreta, aguardo.

## Not translated

Operator tools and logs (`python -m app.manage`, the deploy and backup scripts), and
text written once for one reader in the language they had then (a sit's wind line,
pushes already sent).
