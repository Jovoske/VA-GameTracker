# Nordic Gamekeeper / NG Connect cameras

GameSense has a REST connector for Nordic Gamekeeper accounts, including the APEX
camera family. The request contracts come from Nordic's own web app; they are not
a published developer API. The connector has automated coverage, but a live account
and its first imported photo still need verification. See the
[source evidence and webhook findings](research-nordic-gamekeeper-apex.md).

## Connect after deploying this change

1. Apply the backend migration (`alembic upgrade head` from `backend/`) and deploy
   the matching backend and frontend build together. Migration
   `0035_nordic_gamekeeper` adds Nordic camera/photo identities and allows Nordic
   accounts; it preserves existing accounts and images. The shared setup flow also
   requires `0036_camera_inboxes`; see [all camera setup options](21-camera-setup.md).
2. In GameSense **Settings → Camera logins → Add cameras**, choose **Nordic Gamekeeper** and enter
   the email and password used for the Nordic account. Google/Microsoft-only sign-in
   is not implemented by this connector.
3. Connect. GameSense verifies the login and camera list before saving the encrypted
   password. The first import requests the previous seven days of photos. If the
   pipeline is busy, the next scheduled fetch picks up the camera.
4. Check that the camera appears, its photos have the correct capture times, and
   the usual AI processing completes. Position the camera on the map if the account
   does not supply coordinates.

The existing scheduled fetch and **Check** action include Nordic cameras. Saved
sessions are encrypted cookie jars. Expired authentication is renewed with the saved
login; one failing provider does not stop the other providers in the native fetch.
Removing the login keeps imported photos and disconnects its cameras.

## Import behavior

- Captures retain Nordic's UTC epoch timestamp, rather than their download time.
- Stable camera/photo IDs and file hashes prevent repeated images. Failed downloads
  remain missing image records, are retried with fresh links, and hold the camera's
  import position. They cannot count as an empty wildlife observation.
- User-assigned camera names, positions and retirement status survive syncing.
- This version imports JPEG photos. Videos are skipped; it does not request new
  captures, change camera settings, or subscribe to webhooks.
- A fetch reads at most 100 media pages per camera (36 items per page) and validates
  the vendor's newest-first ordering. It stops after crossing its time boundary. A
  page limit or malformed response is reported as incomplete rather than silently
  advancing the camera's import position.

The web client's public login configuration is read from the official account site
without executing JavaScript. An optional `NORDIC_CLIENT_SECRET` backend setting can
override that configuration if its representation changes. No vendor credential is
embedded in the repository. API cookies are never attached to media requests.

## Webhooks

Nordic's web app exposes **Settings → Integrations → Webhooks**. REST polling is
implemented first because it fits GameSense's current imports and can retrieve
history without exposing a new incoming endpoint. Adding push delivery requires an
actual event sample and verification of the delivery authentication/signature and
retry contract. No webhook was registered by this change.

## Validation

The client, account routing, session handling, timestamp boundaries, retry behavior,
camera ownership and frontend connection flow have automated tests. PostgreSQL
migration/persistence tests require a scratch database; they skip when none is
available. Before marking the connector live, verify the migration and one complete
camera → cloud → GameSense → AI import using the owner's account.
