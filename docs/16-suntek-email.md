# Suntek HC801LTE photos by email

The camera emails each photo over SMTP to a dedicated mailbox. A poller on the GameSense
server reads that mailbox over IMAP, **outbound only**, and drops every JPEG attachment into
the spool that the existing importer (`backend/app/ingestion/ftp_import.py`) already watches.
From there the photo gets the same enrichment, AI detection and forecast treatment as a
SPYPOINT photo.

This replaced the [FTP path](14-suntek-ftp.md) on Db01 on 2026-09-16: Db01 is a protected
company server and no inbound port or router forward can be opened for it. The FTP
receiver and importer code stay in the repository; only the importer is used by this path.

```
camera --SMTP--> mailbox (Gmail) <--IMAP poll-- mail-receiver --> spool/ready --> importer --> app
```

## Pieces

| Piece | Where | Notes |
| --- | --- | --- |
| Mail receiver | `mail-receiver/receiver.py` | standard library only; one process per mailbox and spool |
| Installer (Db01) | `deploy/install-mail.ps1` | NSSM service `GameSenseMail`; idempotent |
| Importer | `backend/app/ingestion/ftp_import.py`, service `GameSenseFTPImport` | unchanged; installed by `deploy/install-ftp.ps1` |
| Tests | `mail-receiver/tests`, `integration-tests/test_suntek_mail_bridge.py` | fake IMAP client; bridge test runs the real importer parser |

Progress is tracked by IMAP UID in `<spool>/.mail-state.json`, not by read/unread flags, so
opening the mailbox by hand never hides a photo from the import. Messages are marked read
afterwards purely for convenience. The importer deduplicates by file hash, so a resent
photo never creates a second image.

Per message: every part that is `image/jpeg` or named `.jpg`/`.jpeg`, is a complete JPEG
(SOI and EOI markers), and is at most 20 MiB becomes its own package. The email `Date`
header becomes the package's `received_at`; the importer still prefers the JPEG's EXIF
capture time when present. Messages without a usable JPEG, or from a sender that fails the
optional `MAIL_FROM_FILTER`, are skipped and logged. A dropped IMAP connection or a full
disk raises and is retried on the next poll without advancing; only unparsable mail is
skipped permanently (logged at ERROR with its UID).

## Mailbox

Create a **dedicated** mailbox for the camera. Do not reuse a personal account: the camera
stores the password in plain text and the poller has full read access.

For Gmail:

1. Create a new Google account for the camera.
2. Turn on 2-Step Verification (Google account, Security).
3. Create an **App password** (Security, 2-Step Verification, App passwords). Google shows
   16 letters in groups of four; spaces do not matter.
4. IMAP is enabled by default on new accounts. If the Gmail settings show it off, turn it on
   (Settings, See all settings, Forwarding and POP/IMAP).

Any other IMAP provider works; set `MAIL_IMAP_HOST`/`MAIL_IMAP_PORT` accordingly.

## Db01 (native Windows) install

`deploy/install-ftp.ps1` must have run once already (it registers the camera and installs
the importer); on Db01 it has. Then create `C:\GameSense\mail.env` (outside the repo, never
in git):

```
MAIL_IMAP_HOST=imap.gmail.com
MAIL_IMAP_PORT=993
MAIL_USERNAME=<camera mailbox address>
MAIL_PASSWORD=<app password>
MAIL_FOLDER=INBOX
MAIL_FROM_FILTER=
MAIL_POLL_SECONDS=60
```

and run, elevated, on Db01 (or from the laptop over WinRM):

```powershell
Invoke-Command -ComputerName Db01 {
    powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\install-mail.ps1
}
```

The script installs the service, then **logs in to the mailbox once before starting it**, so
a wrong password fails loudly here rather than silently in a log. Re-run it after editing
`mail.env`. `deploy/update.ps1` restarts the service on every deploy.

Logs: `C:\GameSense\logs\mail-receiver.log` (poller) and `C:\GameSense\logs\ftp-importer.log`
(importer). Each poll prints one JSON line with `messages/published/skipped/errors` counts.

## Camera firmware: the real prerequisite

Found in the 2021 support thread with Suntek (support@cnsuntek.com, Howard Zhang): this
camera shipped with the **APP-version firmware**, whose menu is only Camera / Video / Setup and
which sends photos to Suntek's cloud for the SuntekCam app. Email (SMTP) and MMS sending exist
only in the **MMSCONFIG-version firmware**, which adds MMS and SMTP menus and is configured
with the MMSCONFIG PC utility writing `Parameter.dat` to the SD card. Neither that firmware nor
the utility was ever supplied; the three firmware files sent in September 2021 were app-route
builds, and the January 2021 one white-screened this board.

**Update, later on 2026-09-16:** Julle reports he now has the MMSCONFIG-version firmware, so
the support request (left as an unsent Gmail draft) is not needed.

So the order is:

1. Flash the MMSCONFIG-version firmware if not already done (SD card, `FWR8012.bin`, power to
   TEST, red LED for ~10 s, then format the card). Afterwards the menu must show MMS and
   SMTP entries; if it white-screens, the build does not match PCB `HC800-4G-6582053_V10`.
2. Get the 4G MMSCONFIG utility. Suntek links it from https://cnsuntek.com/mmsconfig/
   ("4G Series: MMSCONFIG", a Google Drive file). **As of 2026-09-16 both Drive files are
   blocked by Google** ("does not comply with our Terms of Service"); the Wayback Machine
   only has the same Drive links, suntekcamera.gr and unioncam.net have no copy. Sources left:
   the CD/mini-CD in the camera box (the manual says "Load CD into the computer"), the
   firmware package itself (Suntek often bundles a MMSCONFIG folder), or support@cnsuntek.com
   (updated request draft in Gmail Drafts). The same page notes that Gmail may reject
   the camera's SMTP and offers Suntek's own test SMTP account as a workaround; if that
   turns out to be the only server the firmware can talk to, the poller can read any IMAP
   mailbox, so a mailbox at a provider the camera accepts is the fallback.
3. Only then the camera settings below.

## Camera settings

Confirmed from the HC-801LTE manual (2020 edition, pages 21-28): the camera's own SMTP menu
only has SMTP ON/OFF, FTP ON/OFF, Image Size and Country. Server, account, password and
recipient can **only** be set in MMSCONFIG, which saves `Parameter.dat` to the SD card root;
the camera reads it when switched to TEST. The SMTP tab has a `Manual` mode with a Server
Type of `Other`, a `No SSL / SSL / STARTTLS` choice, and Server / Port / Email / Password
fields, so Gmail on 465 with SSL is expressible. Leave the MMS tab OFF and the FTP tab OFF.

MMSCONFIG, SMTP tab (Manual mode):

| Setting | Value |
| --- | --- |
| Send mode | instant / every photo; picture only (video is not imported) |
| SMTP server | `smtp.gmail.com` |
| SMTP port | `465` with SSL on; if the firmware has no SSL switch, try `587` |
| Account / login | the camera mailbox address |
| Password | the app password |
| Send to / receiver | the same camera mailbox address |
| GPRS / APN | the SIM provider's data APN |

Save the settings to the SD card as the manual describes, insert it with the camera off, and
trigger one photo. Before enabling sending, confirm with USB unplugged that the camera can
take a photo and show it on its own screen.

If the camera cannot negotiate TLS with Gmail (2020 firmware), the options are, in order:
port 587 (STARTTLS); a mailbox at a provider that still accepts SMTP AUTH without TLS; or
the [FTP path](14-suntek-ftp.md) on a small rented server outside the company network.

## Verify

1. Send yourself a test mail with a JPEG attached from any mail client to the camera mailbox.
   Within `MAIL_POLL_SECONDS` plus 30 s it should appear under the camera in the app.
2. Send the same mail again: the importer logs `duplicate`, the camera image count stays.
3. Let the camera send one photo. Check its capture time in the app is right; the importer
   log line names the `timestamp_source` (`exif_*` is what you want; `received_at_fallback`
   means the photo carried no EXIF and the email time was used).

## Operations

- **Re-import from the start:** stop `GameSenseMail`, delete `<spool>\.mail-state.json`,
  start it again. The importer's hash check keeps duplicates out.
- **Mailbox full:** Gmail's 15 GB holds years of camera photos; delete old mail from the
  mailbox freely once imported, the spool and app keep the originals.
- **Two receivers on one spool** is prevented by `<spool>\.mail-receiver.lock`; the FTP
  receiver uses its own `staging` and lock, so both could run side by side if ever needed.

## Tests

From `backend` with the development requirements installed:

```sh
python -m pytest -o addopts='' ../mail-receiver/tests ../integration-tests/test_suntek_mail_bridge.py -q
python -m ruff check ../mail-receiver ../integration-tests/test_suntek_mail_bridge.py
```
