# Nordic Gamekeeper APEX PRO integration

Accessed **2026-10-06**. The user confirms the camera works in the native app; the task is integration into GameSense. The initial setup prerequisite is superseded. Research used public sources only: no authenticated API calls, camera mutations, or webhook registrations.

## Finding

**There is an actionable REST integration path and an explicit webhook feature.** The product/support pages did not document them, but the official account web app's publicly delivered JavaScript does. This is a first-party implementation contract, not a published developer API guarantee. Live validation against the user's account remains necessary.

Sources: [official account web app](https://account.nordicgamekeeper.com/) and its [observed JavaScript bundle](https://account.nordicgamekeeper.com/assets/index-DPxt6J1B.js). Function names below are identifiers in that exact minified bundle and may change in another build. Downloaded JavaScript was inspected as text, not executed.

## REST contract observed in the bundle

Base URL: `https://api.nordicgamekeeper.com`. The shared `F1` wrapper sends JSON and a generated UUID in `x-app-id`. Authenticated calls use browser `credentials: include`: this is **cookie-session authentication**, not a verified bearer-token contract.

| Purpose | Observed request and response use |
| --- | --- |
| Email/password sign-in | `POST /oauth/authorize`; JSON `username`, `password`, `client_id` (`webApp`), `client_secret`, `grant_type` (`password`), `rememberMe` (boolean). Function `oB1`. Login UI consumes `expires_at`, then checks `/api/user/me`. |
| Check account | `GET /api/user/me`; UI reads account fields including `roles`. Function `ac`. |
| List cameras | `GET /api/camera/mine`; callers consume `content`, and cameras' `id`, `shortCode`, `displayName`. Function `dM`. |
| Camera details | `GET /api/camera/by-camera-id/{id}`. Function `si`; details page `nL1` passes its result to metadata components. |
| Camera media | `GET /api/camera/{id}/media?page=0&size=36`; `content` contains media and boolean `last` controls further pages. Function `Rr`; camera gallery `WN1`. Zero-based pages. |
| Combined gallery | `GET /api/camera/latest/user?page=0&size=36&mediaType=1,2`. Function `Ri1`; enum meanings are not documented here. |

Metadata component `Zx` reads `status.batteryPercentage`, `status.signalPercentage`, `status.cameraModel`, and `status.created`. Coordinates used by the edit API are `latitude` and `longitude`. `deviceStatus` is a different structure used for alarms/status colors. Optional absent fields remain unknown.

Media fields consumed by the UI are `idString`, `shortCode`, `dateEpoch`, `url`, `thumbnailUrl`, and `tags`. Date rendering (`d3`, `Yi1`) multiplies numeric dates by 1,000, establishing **Unix seconds** for `dateEpoch`. Image/video rendering and the download link use `url` directly; video detection includes `.mp4` and `.mov`. These observations establish field names, not actual account contents or CDN hosts.

Camera cards request `Rr(camera.id, 0, 1)` and label the result Latest image or Latest video (`P$`, `nL1`). This supports the vendor UI's expectation of newest-first media. The client validates nonincreasing timestamps while scanning, stops after a complete page strictly older than `since`, preserves equal-time boundaries, and fails on order/schema violations or its page cap instead of advancing with partial results. No server-side date parameters were found in `Rr`.

## Webhooks exist in the official UI

Navigation includes **Settings → Integrations**, with Webhooks, Add new Webhook, and Webhook URL controls. Observed operations:

- `GET /api/notifications/push/webhook` (`K71`) lists registrations.
- `POST /api/notifications/push/webhook` with JSON `{ "url": "..." }` (`W71`) creates one.
- `DELETE /api/notifications/push/webhook?clientId=...` (`G71`) removes one.

The UI displays `url`, `clientId`, `clientDisplayName`, `createdDate`, `lastUsed`, `failureCounter`, `paused`, and `externalPartner`. **Delivery body, event types, signing/authentication, retry behavior, and whether events include downloadable media remain unverified.** Do not invent a receiver schema. REST polling fits GameSense's existing ingestion path without requiring a public inbound webhook URL.

## Implemented client and limits

`backend/app/ingestion/nordic.py` implements the observed email/password flow, scoped cookie-session persistence, camera metadata, paginated image listing, and bounded downloads. Its `token` property is a serialized cookie jar intended for GameSense's encrypted session storage, not a vendor bearer token.

Optional `NORDIC_CLIENT_SECRET` overrides the web client's published configuration. Otherwise the client fetches only the exact official account host, extracts its `/assets/index-*.js` script path, and parses the observed password-grant literal under size bounds. No downloaded code executes. The value is neither committed nor logged; a changed or ambiguous bundle fails clearly. **The runtime parser was verified against the live public web app on 2026-10-06**, without attempting login or displaying its result value.

Media downloads use a separate client without API credentials, require HTTPS, reject private DNS answers, pin the checked IP with the original Host/TLS SNI, reject redirects, and enforce a byte limit. Synthetic tests cover request shapes, cookie persistence, auth retries, pagination/time boundaries, schema failures, public configuration parsing, and download restrictions. They do not establish successful live APEX synchronization.

Remaining validation: sign in through GameSense, confirm actual camera/media response shapes, verify an original image and capture time, and check session expiry. Google/Microsoft SSO-only accounts require a separately implemented SSO path or a vendor-supported email/password sign-in; this client does not claim SSO support.

## Product context

The [official APEX PRO product page](https://nordicgamekeeper.com/product/apex-pro/) confirms app control, live-photo, supplied NG-SIM and an app-managed subscription. The [APEX guide](https://support.nordicgamekeeper.com/l/en/article/lg0dp5pklz-get-started-with-ng-sim-apex-series) names NG Connect. Neither establishes arbitrary camera-side SMTP/FTP delivery. [NG-SIM FTP/SMTP instructions](https://support.nordicgamekeeper.com/l/en/article/mc4gjtbb8t-which-settings-should-i-fill-into-my-third-party-camera-when-using-ng-sim) concern third-party cameras sending into Nordic Gamekeeper and are not proof of APEX outbound-server configuration.
