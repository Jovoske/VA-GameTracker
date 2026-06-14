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
2. On the phone (same Wi-Fi), open `http://192.168.1.40:8080`.
3. Add to Home Screen as above.

Works for testing. Caveats: only while the laptop is on and on the same network, and it's
HTTP (basic install works; full offline caching wants HTTPS — see below).

### B. Always-on host + HTTPS (the real setup)
Run the **same `compose.yaml`** on a home server or a cheap VPS, behind automatic HTTPS:
- Add a **Caddy** reverse proxy (a few lines) — it gets a free Let's Encrypt cert and
  serves the frontend + API on your domain. Then the phone opens `https://your-domain`.
- No code changes — that's the portability test from `docs/07-deployment.md`.

### C. No server / no static IP — a tunnel
From the laptop (or home server), expose it securely without port-forwarding:
- **Cloudflare Tunnel** (`cloudflared`) → a free `https://*.trycloudflare.com` (or your
  domain) that points at `localhost:8080`. HTTPS out of the box.
- **Tailscale** → a private HTTPS URL reachable from your phone on the Tailscale network.

Either gives you the HTTPS URL that makes the install + offline fully work.

## Production build (Phase 2 polish)
The dev setup serves the Vite dev server. For the best PWA (full offline precaching of
hashed assets via Workbox), switch the frontend container to a **production build**
(`vite build` → static files served by Caddy/nginx). It's a small compose change and
pairs naturally with option B above. Until then, install + app-shell caching already work.
