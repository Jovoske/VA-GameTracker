# Suntek camera FTP receiver

This isolated service accepts passive FTP JPEG uploads for **one camera account**.
It publishes completed uploads to the shared spool consumed by VA-GameTracker.
The camera uses its existing FTP firmware; it does not need email or SuntekCam.
See the [FTP deployment guide](../docs/14-suntek-ftp.md) and
[Compose overlay](../compose.ftp.yaml) for integration.

## Configuration

Set these environment variables before running `python receiver.py`:

| Variable | Default / purpose |
| --- | --- |
| `FTP_USERNAME` | Required dedicated camera login |
| `FTP_PASSWORD` | Required, at least 13 characters; generate a unique password |
| `FTP_SPOOL_ROOT` | Required absolute directory, one per camera |
| `FTP_BIND` | `127.0.0.1`; Docker overlay uses `0.0.0.0` inside the container |
| `FTP_PORT` | `2121`; camera and host port mapping must agree |
| `FTP_PUBLIC_IP` | Optional advertised IPv4 address for passive FTP through NAT; use an IP literal, not a DNS name |
| `FTP_MAX_UPLOAD_BYTES` | `20971520` (20 MiB); may be lowered, never increased above 20 MiB |
| `FTP_MAX_SPOOL_BYTES` | `2147483648` (2 GiB); includes waiting and quarantined files |
| `FTP_MAX_QUEUE_FILES` | `1000` queued JPEG files, including active reservations |
| `FTP_MIN_FREE_BYTES` | `104857600` (100 MiB) additional filesystem reserve |

Passive data ports are fixed to TCP **50000–50009**. Use passive mode and folder
`/` in the camera; no subfolders, listing, downloads, resume, deletion, or active
FTP are available. The service accepts names such as `PICT.JPG` and `.jpeg`.
It returns an FTP failure when capacity is exhausted, so the camera may retry.
Actual camera retry behavior must be tested on the hardware.

This is plain FTP: the camera login and photos are not encrypted in transit.
Use a dedicated camera-only credential, never an app/database/admin password.
The receiver has no database credentials and cannot access the application's
media directory. Publish only its control/data ports on the chosen server after
deciding how that server is reached from the camera's mobile network. The default
host binding stays local until explicitly configured for remote access.

Suntek firmware contains `AT+QFTPCFG="filetype",1`. The Quectel EC2x/EC25 FTP
application note identifies this setting as ASCII mode. For compatibility this
JPEG-only receiver accepts `TYPE A` as well as `TYPE I` and **always preserves
raw uploaded bytes**, without FTP newline conversion. This is intentional
camera-specific behavior, not a general-purpose text FTP server. Hardware
confirmation of this firmware path is still required.

## Delivery and recovery

Each upload writes to a fresh `staging/<uuid>/photo.jpg`, independent of its
original filename. The receiver checks size, JPEG start/end framing, and queue
and free-space limits. Full image decoding is the backend importer's job.
It flushes and fsyncs the JPEG and metadata, then atomically renames the package
to `ready/<uuid>` before sending FTP `226`. Linux also fsyncs directories;
Windows testing exercises atomic visibility and file flushes, but not Linux
directory durability. Deploy on a local persistent Linux filesystem with
working fsync/atomic rename semantics. Network shares are not validated.

Each ready package contains `photo.jpg` and `metadata.json`:

```json
{"version":1,"original_filename":"PICT.JPG","received_at":"2026-09-13T12:00:00+00:00","byte_count":12345}
```

Aborted or obviously truncated transfers never enter `ready`. Like ordinary FTP,
there is no independently declared expected payload size: a client ending its
data connection is the protocol's end-of-file. JPEG framing catches truncation
without an ending marker; the importer rejects images that cannot be decoded.

A failure while publishing returns `451` instead of success. If the final
directory sync fails after atomic rename, a complete item may already be queued;
the sender can retry and the importer must deduplicate. Delivery is at least
once. A receiver restart removes only its uncommitted staging directories and
keeps ready items. A per-spool OS lock prevents two receiver processes from
sharing staging or quota reservations. Never let another service write staging.

The shared spool must allow receiver UID/GID `10001:10001` and the importer to
read/write and rename packages. Monitor receiver logs and quarantine/disk usage;
full queues reject new uploads until processed or deliberately cleaned up.

## Tests

With the repository's backend development environment (pytest and Pillow) and
this folder's requirements installed:

```sh
python -m pytest ftp-receiver/tests -q
```

Tests use real loopback FTP control/data connections. They cover publication
before `226`, repeated and concurrent filenames, exact byte preservation under
camera ASCII mode, interrupted and oversized uploads, forbidden paths/commands,
authentication, publication/fsync failures, queue limits, and spool ownership.
No test opens firewall ports or binds to a public interface.

References: [pyftpdlib 2.2.0](https://pypi.org/project/pyftpdlib/2.2.0/) and
[Quectel EC2x/EC25 FTP(S) application note](https://forums.quectel.com/uploads/short-url/9LS9TopRksF4ZhmZgF3qOGBoPY6.pdf).
