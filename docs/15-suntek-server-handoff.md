# Suntek FTP integration: handoff to the server agent

Continue from branch `codex/suntek-ftp-ingestion`. The user wants this camera's JPEGs in VA-GameTracker without an email mailbox. The source implementation is prepared; no server deployment, firewall change, or firmware flash has been performed. Server access was unavailable during development.

> **Update:** the native Db01 steps below are now scripted in `deploy/install-ftp.ps1`; see
> [the Db01 section of the guide](14-suntek-ftp.md#db01-native-windows-one-shot-install).
> Merging to `main` deploys the code; the script installs the two services. Router
> port-forwarding and the camera-side MMSCONFIG steps are still manual.

## Start with the existing deployment

Read [the recorded deployment handoff](09-handoff.md) and verify it against the server before applying changes. It describes **Db01, Windows Server 2022, a native installation under `C:\GameSense`, PostgreSQL on port 5433, NSSM services, and scheduled pipeline tasks**. Treat those details as recorded context, not freshly verified server state. If still accurate, follow the native installation section of [the FTP guide](14-suntek-ftp.md), not its Docker section.

Fetch this branch into the development checkout, compare it with the deployed revision and any local changes, then integrate it through the existing deployment procedure. Preserve the existing database, media/models, environment, JWT secret, SPYPOINT configuration, and scheduled work. This integration adds no database migration. Do not use the generic README quick start to replace the production installation.

## Work remaining on the server

1. Validate the importer against the deployed backend and its dependencies in a test environment. Run the four PostgreSQL tests described below before importing into the live database.
2. Deploy `backend/app/ingestion/ftp_import.py` and its dependency changes through the normal backend update process. Install `ftp-receiver/requirements.txt` in a separate receiver environment. Keep database credentials out of the receiver's environment.
3. Create one private, persistent **local** spool shared by the receiver and importer; grant both service identities the needed read/write/rename access. The receiver needs no app media access. Reuse the backend's existing database and media configuration for the importer. Windows loopback/file-flush behavior was tested; Linux directory-fsync durability and Windows sudden-power-loss recovery were not tested on the target server. Network-share spools are unvalidated.
4. Run the importer's `list` command from the backend directory using the existing backend environment. Select the actual estate, register one FTP camera if needed, and record its UUID. Configure the camera location and clock timezone; do not reuse a camera linked to SPYPOINT.
5. Configure a unique camera-only FTP account using the [receiver settings](../ftp-receiver/README.md). Start the receiver on loopback and verify a JPEG upload plus importer processing before exposing it. Supervise both processes with the server's existing service-management approach; verify restart behavior and logs. Preserve the existing scheduled AI pipeline.
6. Establish how the camera's mobile network reaches the receiver. Configure a reachable control port and TCP passive ports `50000-50009`, with the correct public IPv4 address advertised in passive replies. The recorded Cloudflare HTTPS tunnel alone does not provide this FTP path. If direct inbound routing is unavailable, resolve receiver placement/routing before configuring the camera.
7. Coordinate the camera-side steps below with the user, then run the acceptance checks in [the FTP guide](14-suntek-ftp.md#verify-before-leaving-the-camera-unattended). Record deployment revision, service names, spool path, camera UUID, and results in a handoff without committing credentials.

If the deployment has moved to Docker, retain its actual Compose project name, override files, database, and media mounts when adapting `compose.ftp.yaml`. The overlay has only been parsed as YAML, not built or run locally.

## Camera-side handoff to the user

Server access alone cannot complete the camera setup. Someone at the camera must load the generated `Parameter.dat` using the compatible MMSCONFIG utility and trigger the first photo. Give the user the receiver address, control port, folder `/`, and dedicated account details through an appropriate private channel. FTP credentials and photo traffic are unencrypted; do not reuse a server or app password.

Confirm the SIM's APN/data service and the camera clock/timezone. With USB disconnected, first verify that the SD card can save and display a photo; USB previously reported mass storage but no usable media. Then enable FTP and test one JPEG. Video import is outside this integration.

The camera's reported version is `EC25E 10/20/2020-P3`; its photographed board is `HC800-4G-6582053_V10`. Keep the working firmware. The older APP firmware previously produced a white screen, and the inspected replacement firmware files did not establish a compatible enabled SuntekCam path. This FTP setup does not require firmware changes. Private support emails and firmware archives are not part of this source change.

## Validation to complete

Local result: **70 passed, 4 PostgreSQL tests skipped**. Ruff and Python compilation passed. Tests include real loopback FTP transfers, ASCII/binary JPEG byte preservation, interrupted/concurrent uploads, queue failure paths, and transfer-to-importer parsing. A real camera upload, database-to-gallery flow, target service restart, external passive routing, and target filesystem recovery remain unverified.

From `backend`, with backend development and receiver dependencies installed:

```sh
python -m pytest -o addopts='' tests/test_ftp_import.py ../ftp-receiver/tests ../integration-tests -q
python -m ruff check app/ingestion/ftp_import.py tests/test_ftp_import.py ../ftp-receiver ../integration-tests
```

Set `GAMESENSE_REQUIRE_DB=1` and `GAMESENSE_TEST_DSN` to a **separate scratch PostgreSQL instance** whose test account can create/drop databases. The current shared fixture builds temporary database URLs by replacing `/postgres?`, so the DSN must contain that exact segment, for example `postgresql+psycopg://TEST_USER:TEST_PASSWORD@127.0.0.1:55432/postgres?connect_timeout=5`, using the actual scratch port and credentials. Do not point these tests at the production database or change the live PostgreSQL port. Inspect `backend/tests/conftest.py` before running them; temporary test databases are created and dropped.

For the live acceptance test, confirm the photo belongs to the correct camera, has a readable original and correct timestamp/timezone, appears only once when resent, and reaches the existing AI pipeline. Stop only the newly added FTP services to roll back their operation; retain the spool and imported originals. Review the guide's explicit recovery procedure before retrying failed or interrupted importer work.

## Deployment record: Db01, 2026-09-16

The server side is installed and verified. Everything below was done from the
laptop over WinRM against the deployed revision `14254a5`.

| Item | Value |
| --- | --- |
| Config | `C:\GameSense\ftp.env` (outside the repo; holds the only copy of the FTP password) |
| Services | `GameSenseFTP` (receiver) and `GameSenseFTPImport` (importer), NSSM, auto-start, both running |
| Spool | `C:\GameSense\data\ftp-spool` |
| Logs | `C:\GameSense\logs\ftp-receiver.log`, `C:\GameSense\logs\ftp-importer.log` |
| Camera in app | "Suntek HC801LTE", id `3bf1c949-e6c3-4a42-825f-2890de499052`, estate Piedras Lisas, timezone Europe/Madrid |
| FTP account | `suntek-01` (password in `ftp.env` only; never commit it) |
| Bind / port | `0.0.0.0:2121`, passive TCP 50000-50009, advertised public IP `217.67.227.28` |
| Windows Firewall | inbound rules "GameSense FTP control" and "GameSense FTP passive", enabled |
| Db01 LAN address | `192.168.10.9`, gateway `192.168.10.1` |

Verified:

- Installer loopback smoke test passed twice (before and after switching to `0.0.0.0`).
- A JPEG uploaded from another LAN host (`192.168.10.120`) became a `ready` package,
  was imported within 30 s, and is visible under the camera in the app with a working
  `/file` download. The importer logged `received_at_fallback` because the test file
  had no EXIF; check that the first real camera photo carries a capture time.
- Re-sending the identical file was counted as `duplicate`; the camera still shows one image.
- The test image `4741480a-d6e6-4d55-8895-2ca16e6b839a` was flagged as an empty frame.
- Port 2121 is reachable from another LAN host, so the Windows Firewall rules work.
- The public address `217.67.227.28:2121` does **not** connect from inside the LAN.
  Expected: no router forward exists yet (and/or no hairpin NAT).
- The router answers no UPnP discovery, so the forward must be added by hand.

### Remaining steps (manual)

1. **Router** at `192.168.10.1`: forward TCP `2121` and TCP `50000-50009` to `192.168.10.9`.
   Confirm its WAN page shows `217.67.227.28`. A `10.x` or `100.64.x` WAN address means
   carrier-grade NAT, and inbound FTP will not work without a different arrangement.
2. **Outside-LAN test**: from a phone hotspot, any FTP client, passive mode, folder `/`,
   account `suntek-01`, upload a JPEG. It should appear under the camera in the app.
3. **Camera** via MMSCONFIG and the `Parameter.dat` SD-card workflow (keep the firmware):
   FTP enabled, server `217.67.227.28`, port `2121`, folder `/`, account `suntek-01`,
   password from `ftp.env`, photo-only capture, correct SIM APN. First confirm, with USB
   unplugged, that the camera saves and shows a photo on its SD card. Then trigger one photo
   and watch the two logs above.
4. **Map**: place the camera in the app so enrichment uses the right location.
5. If the public IP turns out to be dynamic, the camera's server setting will break when it
   changes; the receiver advertises an IP literal in passive replies, so a DDNS name alone
   is not enough. Revisit before relying on it.

To change any FTP setting: edit `C:\GameSense\ftp.env` and re-run
`deploy\install-ftp.ps1` elevated on Db01 (idempotent). `deploy/update.ps1` restarts both
services on every deploy.

## Change of route: email, 2026-09-16 (later the same day)

Db01 is a protected company server: no router forward or inbound port can be arranged for
it, so the FTP path above cannot receive from the camera. Db01 has unrestricted outbound
access (checked: TCP 22, 443, 993 and 465 all reachable), so the camera now delivers by
**email** and Db01 polls the mailbox. See [16-suntek-email.md](16-suntek-email.md).

Done on Db01:

- `GameSenseFTP` receiver service removed; the two "GameSense FTP" firewall rules removed;
  `ftp.env` set back to `FTP_BIND=127.0.0.1` with no public IP. Nothing listens on 2121.
- `GameSenseFTPImport` (the importer) kept running; it is what the email path feeds.
- Camera record, spool and FTP account unchanged (the account is unused now).

Still to do:

1. Create the dedicated camera mailbox and its app password (Gmail: 2-Step Verification,
   then App password).
2. Write `C:\GameSense\mail.env` and run `deploy\install-mail.ps1` on Db01. It fails if the
   mailbox login does not work, before starting anything.
3. Email a JPEG to the mailbox and confirm it appears under the camera in the app.
4. Configure the camera's SMTP settings in MMSCONFIG and trigger one photo.
5. Place the camera on the map.

### Email path installed and verified on Db01, 2026-09-16

- Mailbox: `FoxCam.Suntek@gmail.com` (dedicated account, 2-Step Verification on, app
  password in `C:\GameSense\mail.env` only). Google refused the plain account password over
  IMAP, as expected; the app password works.
- `deploy\install-mail.ps1` run: service `GameSenseMail` running, auto-start, log
  `C:\GameSense\logs\mail-receiver.log`. It correctly skipped Google's three welcome mails.
- End-to-end test through the camera's exact path: a JPEG with EXIF capture time sent from the
  camera account to itself over `smtp.gmail.com:465` (SSL, app password) was polled within a
  minute, imported by `GameSenseFTPImport` with `timestamp_source=exif_with_offset`, and shows
  under the camera in the app with the right capture time (12:40 Europe/Madrid). Test image
  `6b14ad96-e3a9-4073-ad11-ffa39f62ad06` flagged as an empty frame.

Remaining: camera SMTP settings in MMSCONFIG (values printed by the installer and listed in
[16-suntek-email.md](16-suntek-email.md)), first real photo, place the camera on the map.
