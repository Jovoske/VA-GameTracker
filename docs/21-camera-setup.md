# Add cameras in Settings

Deploy the matching backend and frontend and run `alembic upgrade head` through
`0036_camera_inboxes` before using the new form. Existing logins keep their credentials,
camera associations and photo history. No production deployment or live account
verification has been performed by this implementation.

Open **Settings → Camera logins → Add cameras**. Select a brand or protocol; only its
fields appear. Switching providers clears the credentials. **Check and connect**
verifies access before saving the encrypted password. Successful connections start
an import, or wait for the next scheduled fetch if the pipeline is busy.

| Choice | Required information |
| --- | --- |
| SPYPOINT | Account email and password; optional connection name |
| Nordic Gamekeeper | NG account email and password; optional connection name |
| UBox Pro | Account email and password; per-camera import interval and daily limit |
| Suntek email | Camera name, receiving mailbox credentials, public IMAP hostname, TLS port, dedicated folder and camera timezone; optional exact sender address |
| Suntek FTP / FTPS | Camera name, existing public FTP server, port, dedicated absolute folder, read credentials, transport and camera timezone |

Members can add cloud logins. Admins can also configure email and FTP endpoints.
Viewers cannot add connections. The existing ownership rules apply to password
replacement and removal. Removing a connection stops imports and keeps its photos.

## Nordic Gamekeeper

See [Nordic setup and verification](20-nordic-gamekeeper.md). This connector uses the
REST API observed in NG Connect's web client. It does not register a webhook.
Google/Microsoft-only sign-in is not supported; use the account's email/password login.

## Suntek email

Configure the camera to send JPEG photos to a mailbox you control. Use a dedicated
mailbox or route this camera's mail to its own folder. Enter the **receiving mailbox**
credentials in GameSense, not the camera's outgoing SMTP credentials. Providers may
require an app password and IMAP to be enabled. OAuth-only mailboxes are not supported.
IMAP uses certificate-verified TLS (normally port 993).

GameSense reads up to 50 messages per check, starting with the oldest messages in
the selected folder on first connection. It uses message UIDs and UIDVALIDITY for
progress, fetches with BODY.PEEK, and neither marks mail read nor deletes messages.
An optional sender filter matches one exact address. One folder can be connected
only once for a given mailbox/server; use separate folders for separate cameras.

## Suntek FTP / FTPS

The form connects to an **existing server that receives the camera's uploads**.
It does not install or expose a new FTP listener on GameSense. Configure the camera
to upload to its own folder on that server, then give GameSense an account that can
list and download that folder. The existing standalone GameSense upload-only FTP
bridge cannot be used as this read endpoint; its established setup remains separate.

The FTP server must support MLSD, SIZE, passive downloads and JPEG files. FTPS uses
explicit TLS (normally port 21), certificate verification and an encrypted data
channel. SFTP and implicit FTPS are not supported. Plain FTP is selectable for
legacy servers, with its lack of encryption explained in the form.

Checks rotate through at most 50 JPEG files from a folder of at most 10,000 entries.
Changed file size/modification time triggers another download. Use unique filenames
on the camera: replacing a file with the same size and timestamp is not detectable.
If modification times are unavailable, files are downloaded again and deduplicated
by content. Partial uploads are retried. GameSense does not delete remote files;
archive older files on the FTP server as needed.

## Import and recovery

Photos are staged below `camera-inboxes/<account UUID>` beside `MODELS_ROOT`, then
passed through the existing JPEG validation, timestamp correction, duplicate
detection, enrichment and AI pipeline. Limits are 20 MB per photo and 32 MB per
email. Each inbox creates one estate-scoped camera. Set its position on the map
after connecting; local inboxes do not supply cloud battery or signal telemetry.

Progress advances only after staging. Per-account locks prevent concurrent inbox
workers, and the next worker recovers packages left in `processing` after a crash.
Transient database/disk failures remain queued. Invalid packages are kept in
`failed`, and the connection shows an error. An operator can inspect their
`error.json`, fix the cause and use the existing `app.ingestion.ftp_import retry
--spool <account spool>` command. Do not manually import/recover these per-account
spools while an inbox worker is running.

## Validation boundary

Automated tests cover dynamic fields, all five payloads, validation, rejected logins,
duplicate submission, refresh failures, role restrictions, mobile layouts, mailbox
progress, partial FTP uploads, pinned public connections and durable queue format.
PostgreSQL migration and persistence tests require `GAMESENSE_TEST_DSN` pointing to
a scratch database. They are skipped locally when that database is unavailable.
Before production rollout, run those database tests and verify one real imported
photo from each configured provider/inbox.
