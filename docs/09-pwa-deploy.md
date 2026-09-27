# Installing GameSense on your iPhone (and hosting it)

GameSense is a **browser-based PWA** — no App Store, no Apple account. You install it
straight from Safari. This covers (1) the install steps and (2) how to make it reachable
from your phone.

## 1. Install on your iPhone

1. Open the GameSense URL in **Safari** on the iPhone.
2. Tap the **Share** button → **Add to Home Screen**.
3. It installs with the GameSense icon and opens **full-screen**, like a native app.

That's it — it's now on your home screen. (The manifest + service worker are already built in.)

## 2. Making it reachable from your phone

The phone has to be able to *open* the URL. Three options, easiest first:

### A. Same Wi-Fi (quick test, today)
While the laptop is running the stack:
1. Find the laptop's LAN IP: `ipconfig` → the IPv4 address (e.g. `192.168.1.40`).
2. Start the stack with `WEB_BIND=0.0.0.0` (compose.yaml publishes only on this
   machine otherwise), then on the phone (same Wi-Fi) open `http://192.168.1.40:8080`.
3. Add to Home Screen as above.

Works for testing. Caveats: only while the laptop is on and on the same network, and it's
HTTP (basic install works; full offline caching wants HTTPS — see below).

### B. Always-on host + HTTPS (the real setup)
`compose.yaml` is the development stack (default database credentials, `--reload`,
ports on 127.0.0.1 only): don't run it as a server as it stands. The estate's server is
Db01, native Windows (`docs/09-handoff.md`). For another always-on host, behind HTTPS:
- Add a **Caddy** reverse proxy (a few lines) — it gets a free Let's Encrypt cert and
  serves the frontend + API on your domain. Then the phone opens `https://your-domain`.
- No code changes — that's the portability test from `docs/07-deployment.md`.

### C. No server / no static IP — a tunnel
From the laptop (or home server), expose it securely without port-forwarding:
- **Cloudflare Tunnel** (`cloudflared`) → a free `https://*.trycloudflare.com` (or your
  domain) that points at `localhost:8080`. HTTPS out of the box.
- **Tailscale** → a private HTTPS URL reachable from your phone on the Tailscale network.

Either gives you the HTTPS URL that makes the install + offline fully work.

## Offline, updates and crashes (what the built app does)

`npm run build` stamps `dist/sw.js` with the build id and the list of every built
file (`vite.config.ts`). Serve `dist` the way Db01 does (the API with `FRONTEND_DIST`
set; `backend/app/frontend.py` sends the right cache headers) and:

- **First visit is enough.** The service worker stores the whole app when it installs,
  the map included, so the next launch opens with no signal at all.
- **No signal, one bar, or the server/tunnel down** (a 5xx or Cloudflare 52x/530) all
  look the same to the hunter: the stored app opens within about 3 s, and Tonight,
  Stands and Sit mode show the last saved copy at once with its real age, for example
  "No signal. Plan from 14 h ago." or, while the network is still being asked,
  "Stands from 1 d ago. Checking…". A plan from an earlier night says so, and Stands
  never shows an earlier night's reservations as tonight's ("Tonight not known yet",
  no Reserve). Photos and Cameras say when they show what the phone saw earlier.
- **Deploys.** Each build is a new service worker. It takes over only once it has
  stored the page and every file the page names; on a signal too weak for that the
  old one stays and the phone tries again later. A phone with the app open is told
  "A new version of GameSense is ready" with a Reload button; until then it keeps the
  previous build's files, so it can still open the map. Without a service worker, a
  page whose file was deleted reloads once by itself.
- **Nothing goes blank.** A page that breaks shows "Something broke. Reload" with the
  tab bar still there, and drops only its own saved copies (a bug on Photos never
  costs the plan saved for tonight). Every crash, and every page that didn't load, is
  reported to the server log and listed for admins under Settings → Problems on
  phones, with when it happened on the phone (a report waits there for signal).

Set `GS_BUILD` when building to choose the build id; otherwise it is the build time.
