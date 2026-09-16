# Suntek camera mailbox receiver

Polls one IMAP mailbox (outbound only) and publishes every JPEG attachment as a
`ready/<hex>/{photo.jpg,metadata.json}` package in the spool consumed by the
GameSense importer. Standard library only; no port is opened. See
[the email guide](../docs/16-suntek-email.md).

| Variable | Default / purpose |
| --- | --- |
| `MAIL_IMAP_HOST` | Required, e.g. `imap.gmail.com` |
| `MAIL_IMAP_PORT` | `993` (IMAP over TLS) |
| `MAIL_USERNAME` | Required mailbox address |
| `MAIL_PASSWORD` | Required (Gmail: an App password) |
| `MAIL_FOLDER` | `INBOX` |
| `MAIL_SPOOL_ROOT` | Required absolute spool directory shared with the importer |
| `MAIL_POLL_SECONDS` | `60`; backs off exponentially (max 30 min) while the mailbox is unreachable |
| `MAIL_FROM_FILTER` | Optional; only messages whose From contains this text are imported |
| `MAIL_MARK_SEEN` | `1`; mark imported mail read (cosmetic) |
| `MAIL_MAX_UPLOAD_BYTES` | `20971520` (20 MiB), never higher |

Run `python receiver.py` (loop) or `python receiver.py --once` (single poll, exit code 1
on a connection/login failure). Progress lives in `<spool>/.mail-state.json` (IMAP
UIDVALIDITY + last UID); delete it to re-import everything, the importer's hash check
prevents duplicates. `<spool>/.mail-receiver.lock` keeps a second poller off the spool.

Tests: `python -m pytest mail-receiver/tests -q` (fake IMAP client, no network).
