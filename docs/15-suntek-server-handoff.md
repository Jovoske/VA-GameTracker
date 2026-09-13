# Suntek FTP integration: handoff to the server agent

Continue from branch `codex/suntek-ftp-ingestion`. The user wants this camera's JPEGs in VA-GameTracker without an email mailbox. The source implementation is prepared; no server deployment, firewall change, or firmware flash has been performed. Server access was unavailable during development.

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
