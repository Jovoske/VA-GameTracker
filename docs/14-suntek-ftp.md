# Suntek HC801LTE photo uploads

This adds a photo-only FTP input to GameSense/VA-GameTracker. The camera keeps its working firmware. Its mobile-data connection sends JPEGs to an FTP receiver; a separate importer adds them to the existing camera gallery and image-processing pipeline. No Suntek cloud or email mailbox is involved.

The receiver and importer are optional. This change does not open ports, configure a camera, or deploy services by itself. The actual camera and remote server still require a first transfer test.

For the agent continuing installation on the project's server, start with the [server handoff](15-suntek-server-handoff.md), including the recorded native Windows deployment and remaining acceptance checks.

## What must be available on the server

- Access to the existing GameSense installation and its database, with permission to run two additional processes.
- An internet-reachable FTP control port and passive data ports. A normal website URL or HTTPS tunnel alone does not carry FTP. A server behind carrier-grade NAT needs a separately reachable receiver or an appropriate network arrangement.
- A dedicated account for this camera, and a private spool directory shared between the receiver and importer. Use one account/service/spool per camera in this initial implementation.
- A working camera SD card, active SIM data, correct APN, and the camera clock/timezone set correctly.

This old camera's FTP support is established; FTPS/SFTP support is not. The provided receiver uses plain FTP, so its dedicated credentials must not be reused for the app, server, or email. The camera account can upload JPEGs only and cannot download or delete files. FTP service traffic is separate from the app/database, which should not be exposed for camera uploads.

## Docker installation

Use this section only if the existing app already runs using this repository's `compose.yaml`. For a native Windows/Linux installation, use the next section instead; do not create a second empty app/database with Docker.

Run from the existing deployment checkout and retain its Compose project name, environment files, and any override files. The examples below assume the standard repository stack; adapt them to the live deployment so `db` and the media mounts refer to its existing data.

1. Install this source revision on the server using the app's normal update procedure. Rebuild the backend image so the importer and explicit Pillow/timezone dependencies are available. Keep the existing database and media volumes.

2. List existing estates and cameras, then register a camera if needed. These commands use the base compose file so a camera ID is not required before registration:

   ```sh
   docker compose run --rm --no-deps api python -m app.ingestion.ftp_import list
   docker compose run --rm --no-deps api python -m app.ingestion.ftp_import register --estate-id ESTATE_UUID --name "Suntek HC801LTE"
   ```

   Replace `ESTATE_UUID` with the estate ID from `list`. Record the returned camera UUID. Reuse that UUID for all subsequent imports; do not register a new camera on every restart. Set its location in the app so weather/enrichment use the correct site.

3. Copy `.env.ftp.example` to `.env.ftp.local` (gitignored). Fill in a unique FTP username, a long random camera-only password, the camera UUID, and the timezone matching the camera's clock. Do not reuse the app login password.

   `FTP_BIND_ADDRESS=127.0.0.1` permits local testing only. On the actual server, choose its listening interface (or `0.0.0.0` when appropriate), set `FTP_PUBLIC_IP` to the public IPv4 address used by the camera, and choose `FTP_CONTROL_PORT` (for example `21` or `2121`). Behind NAT, the passive reply must advertise that same reachable public IP.

4. Start just the optional services with the existing app:

   ```sh
   docker compose --env-file .env --env-file .env.ftp.local -f compose.yaml -f compose.ftp.yaml up -d --build ftp-receiver ftp-importer
   ```

   Configure the server/router firewall for the selected TCP control port and TCP `50000-50009` to this receiver. Preserve passive port numbers through NAT. Do this only after the receiver account is configured and the local upload test below passes. Never forward PostgreSQL or Redis for the camera.

5. Inspect receiver and importer output:

   ```sh
   docker compose --env-file .env --env-file .env.ftp.local -f compose.yaml -f compose.ftp.yaml logs --tail 100 ftp-receiver ftp-importer
   ```

The importer checks for completed uploads every 30 seconds. The app's existing AI jobs process imported photos on their usual schedule; a photo appearing in the gallery does not mean species recognition has already finished.

## Db01 (native Windows) one-shot install

> **Done on Db01 on 2026-09-16.** Services installed, firewall open, LAN upload verified.
> See the [deployment record](15-suntek-server-handoff.md#deployment-record-db01-2026-09-16)
> for the camera id, paths, and the manual steps that remain (router forward, camera config).

Production runs natively on Db01, so the code arrives by the normal push-to-`main` loop
([deployment](09-deployment.md)); this section is the rest. Once Db01 has pulled a `main`
that contains `ftp-receiver/`, create `C:\GameSense\ftp.env` (outside the repo; the header of
`deploy/install-ftp.ps1` lists its keys) and run, elevated, on Db01:

```powershell
Invoke-Command -ComputerName Db01 {
    powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\install-ftp.ps1
}
```

It creates the spool `C:\GameSense\data\ftp-spool` and a receiver-only venv, registers the
camera in the app (filling `FTP_CAMERA_ID` back into `ftp.env`), installs the auto-start NSSM
services `GameSenseFTP` (receiver, logs to `C:\GameSense\logs\ftp-receiver.log`) and
`GameSenseFTPImport` (importer, `ftp-importer.log`), proves a loopback upload lands as a
`ready` package before the importer starts, and opens Windows Firewall for the control port
and TCP 50000-50009 when `FTP_BIND` is not loopback. Re-run it after editing `ftp.env`.
`deploy/update.ps1` restarts both services on every later deploy.

Run it first with the default `FTP_BIND=127.0.0.1`; then set `FTP_BIND=0.0.0.0` and
`FTP_PUBLIC_IP`, re-run, forward the ports on the router, and test from outside the LAN
before touching the camera. The router forwarding and the camera's MMSCONFIG settings
remain manual steps.

## Native Windows/Linux installation

Use the existing backend Python environment and database configuration. Update backend dependencies from `backend/requirements.txt`. Install the receiver's small dependency list in its own virtual environment using `pip install -r ftp-receiver/requirements.txt`.

From the `backend` directory, with its usual `.env` present:

```sh
python -m app.ingestion.ftp_import list
python -m app.ingestion.ftp_import register --estate-id ESTATE_UUID --name "Suntek HC801LTE"
python -m app.ingestion.ftp_import run --camera-id CAMERA_UUID --spool ABSOLUTE_SPOOL_PATH --timezone Europe/Madrid --watch --interval 30
```

Replace the UUIDs, absolute spool path and timezone. The importer needs the existing app's database credentials and media path; the receiver does not. Run the receiver and importer as supervised processes (the server's service manager or Windows service/task arrangement), with automatic restart and access to the same spool. See [receiver configuration](../ftp-receiver/README.md) for its exact command/environment variables. Its defaults bind to loopback only.

The existing native `pipeline.py sync` continues to process imported photos during its normal AI pass. There is no need to configure Celery solely for FTP. No Windows tasks or Linux services are registered automatically by this change.

## Camera settings

Use the compatible MMSCONFIG 4G utility for this camera and its documented SD-card `Parameter.dat` workflow. No firmware `.bin` belongs on the SD card for this setup.

| Setting | Value |
| --- | --- |
| FTP | Enabled |
| Server | Receiver's public IPv4 address or compatible hostname; not the app's web page URL |
| Port | Public control port configured above, usually 21 or 2121 |
| Path/folder | `/` |
| Account | Dedicated `FTP_USERNAME` |
| Password | Dedicated `FTP_PASSWORD` |
| GPRS/APN | Correct mobile-data APN and any required APN credentials for the SIM provider |
| Capture mode for first test | One JPEG photo; video uploads are not supported by this importer |

The [HC-801LTE manual](https://suntekcamera.gr/wp-content/uploads/2020/07/HC-801LTE-User-Manual.pdf) documents FTP settings within MMSCONFIG and FTP ON/OFF in the SMTP menu. Firmware/menu revisions vary. Use the FTP sending option and preserve its shared GPRS settings. Once configuration is saved, insert the card while the camera is off and follow the manual's TEST-mode configuration loading procedure. Do not format a card containing wanted photos.

## Verify before leaving the camera unattended

1. With USB disconnected, take and review a photo on the camera. Resolve any SD-card recording error first.
2. Test the receiver locally with a JPEG and the dedicated FTP account, in passive mode. Verify the upload gets a successful FTP response and becomes a completed spool package.
3. Test through a different internet connection. A local-only success does not verify router/NAT/passive-port routing.
4. Let the camera send one new photo. Verify one importer record, its camera association, readable image, capture timestamp/timezone, and eventual AI processing in the app.
5. Repeat the same file upload: it should not create a duplicate Image. Interrupt an upload: it must not appear as a completed image.

The importer records timestamp provenance in its local metadata. EXIF time or a recognized camera filename is preferred; a received-time fallback, if used, must be reviewed because delayed cellular uploads can make arrival time differ from capture time.

## Queue operations

Only atomically published `ready` packages are eligible for import. `staging` contains incomplete transfers; `processing` holds claimed work; `failed` preserves rejected/failed imports with their error information; successful packages retain audit metadata under `processed`. The media original is saved independently before the database import is committed.

Temporary database connection outages return the current package to `ready`; a watched importer retries it on the next poll. Other rejected/failed packages require the importer's `retry --spool ABSOLUTE_SPOOL_PATH` command after fixing their cause. To recover a crashed importer, first stop **all** importers, then run `recover --spool ABSOLUTE_SPOOL_PATH --workers-stopped` before restarting. Never reclaim live `processing` work.

The receiver has queue and disk limits. Monitor failed packages and available space; accepted uploads remain queued when the app/database is unavailable. Do not erase a spool as a troubleshooting shortcut. Stop the receiver and importer when changing the camera-to-spool binding, and finish the old camera's queue first.

## Validation status

The combined local test run passed **70 tests**. **Four PostgreSQL integration tests were skipped** because a scratch PostgreSQL server is unavailable here. Tests include actual loopback FTP control/data transfers in TYPE A and TYPE I, interrupted/concurrent uploads, queue publication failures, JPEG/time parsing, and transfer-to-importer parsing. They do not verify database concurrency or a live camera-to-gallery flow. Ruff and Python compilation checks pass; the Compose overlay parses as YAML, but a Docker engine is unavailable for a container build/run test.

To repeat the automated checks from `backend` with development/receiver dependencies installed:

```sh
python -m pytest -o addopts='' tests/test_ftp_import.py ../ftp-receiver/tests ../integration-tests -q
python -m ruff check app/ingestion/ftp_import.py tests/test_ftp_import.py ../ftp-receiver ../integration-tests
```

Set `GAMESENSE_TEST_DSN` to a scratch PostgreSQL database and `GAMESENSE_REQUIRE_DB=1` to require the four database tests. The real camera, server deployment, passive NAT routing, and first database-to-gallery transfer must still be verified at installation.
