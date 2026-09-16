The `synthetic_*` fixtures are **synthetic**, based on field structures documented in
[JEMcats/ubox_camera_api](https://github.com/JEMcats/ubox_camera_api).
They are not recordings from a real UBox account and do not establish snapshot
availability, signal scale, event timezone behavior, rate limits or retention.

The `live_*_redacted.json` fixtures were captured on 2026-09-16 from the authorized
UBox Pro account (`app=uboxpro`). Identifiers are salted hashes; credentials, URLs,
SIM identifiers, names and locations are redacted. They verify one model2592
device response and a 15-event page. Both snapshot fields returned real JPEGs in
the separate probe; see the handoff for dimensions. These samples do not establish
future access after a cloud trial, retention or signal scale. No image bytes or
usable account/session identifiers are included.

An operator can capture a scrubbed real response with
`python -m app.ingestion.ubox_probe --output tests/fixtures/ubox/probe.json`
from `backend/`. Credentials are prompted without echo; no credentials are written.
The probe hashes identifiers with a fresh per-run secret and redacts URLs, device
passwords, names, locations, SIM/account identifiers and all unknown text fields.
Review its output before committing any real fixture. Image bytes are never included.
