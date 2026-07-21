# Hosting GameSense on Db01 — the runbook

From a clean Linux install to the app running 24/7, phone-installable, with the full
photo archive. This is Phase 2 of `docs/07-deployment.md`, made concrete. Everything
below is copy-paste; only `.env` values are yours to fill in.

Assumes: Debian/Ubuntu-family Linux on Db01 and SSH access with sudo. (Any distro
works — only step 1's package commands differ.)

## 1. One-time server prep

```bash
# Docker Engine + Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out & back in for this to apply

# Folder for the photo archive — put it on the biggest disk
sudo mkdir -p /srv/gamesense/media
```

Check: `docker compose version` → needs **v2.24 or newer** (the overlay uses the
`!override` tag).

## 2. Get the code and configure

```bash
git clone https://github.com/Jovoske/VA-GameTracker.git
cd VA-GameTracker
cp .env.production.example .env
nano .env
```

Fill in every `change-me` (`openssl rand -hex 32` makes good secrets), your SPYPOINT
credentials, and check `MEDIA_PATH` points at the folder from step 1.

## 3. Start it

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

First build takes a while (the AI stack). Then:

```bash
docker compose ps                                  # all services healthy?
curl -s http://localhost/api/health                # {"status":"ok"}
```

Open `http://<db01-ip>` and log in with the admin credentials from `.env`.

What the overlay changed vs the laptop stack: production frontend build served by
Caddy (no Vite dev server), no source mounts or auto-reload, Postgres/Redis/API not
exposed to the network (only Caddy is), `restart: unless-stopped` everywhere, and the
media archive bound to `MEDIA_PATH` with retention ≥ 365 days.

## 4. Reaching it from the phone (pick one)

| Option | When | How |
|---|---|---|
| **LAN only** | Phone on home Wi-Fi | Open `http://<db01-ip>`, Add to Home Screen. HTTP, so offline caching is limited. |
| **Tailscale** (recommended, no ports opened) | Access from anywhere, private | Install Tailscale on Db01 + phone; `tailscale cert` or just use the tailnet IP/name. |
| **Own domain + HTTPS** | You have a domain and can port-forward 80/443 | Point an A record at your public IP, forward 80/443 to Db01, set `DOMAIN=...` in `.env`, re-run the `up -d` command. Caddy gets the certificate automatically. |
| **Cloudflare Tunnel** | Public HTTPS without port-forwarding | `cloudflared tunnel` on Db01 pointing at `http://localhost:80`. |

With HTTPS (any of the last three), the PWA install is fully offline-capable
(`docs/09-pwa-deploy.md`).

## 5. Backups (do not skip)

```bash
# /etc/cron.d/gamesense-backup  (adjust paths/destination)
15 3 * * * root docker compose -f /home/USER/VA-GameTracker/compose.yaml exec -T db pg_dump -U gamesense gamesense | gzip > /srv/gamesense/backups/db-$(date +\%a).sql.gz
45 3 * * * root rsync -a --delete /srv/gamesense/media/ /mnt/backup-disk/gamesense-media/
```

Nightly `pg_dump` (7 rotating daily files) + media rsync to a second disk/location.
Restore = `gunzip -c dump.sql.gz | docker compose exec -T db psql -U gamesense gamesense`.

## 6. Updating

```bash
git pull
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Migrations run automatically on start. (This is exactly what the Admin → self-update
panel automates — `docs/08-git-update.md`.)

## Troubleshooting

- **`MEDIA_PATH` error on start** — the overlay refuses to run without it; set it in
  `.env` and make sure the directory exists.
- **Port 80 already in use** — set `HTTP_PORT`/`HTTPS_PORT` in `.env`.
- **No certificate with `DOMAIN` set** — ports 80/443 must be reachable from the
  internet and the DNS record must point here; check `docker compose logs frontend`.
- **Laptop → server data move** — fresh start is simplest (re-sync from SPYPOINT).
  To keep history: `pg_dump` on the laptop, restore here, copy the media folder into
  `MEDIA_PATH`.
