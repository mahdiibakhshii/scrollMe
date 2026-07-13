# Deployment

ScrollMe runs as a **second app on the existing CityLeaks Hetzner VPS**: its own
PM2 process + nginx server block on a dedicated port, so it never collides with
CityLeaks (which owns `:80`/`:443` and node on `:3000`). GitHub Actions
auto-deploys on every push to `main`.

```
audience phones ──HTTP/WS──▶ nginx :8080 ──proxy──▶ Python aiohttp/Socket.IO 127.0.0.1:8081  (PM2: "scrollme")
TouchDesigner (laptop) ──WS──▶ ws://<ip>:8080/ws ────────────────────────────────┘
GitHub push to main ─▶ Actions: SSH ─▶ git pull + pip install + pm2 restart
```

Public URL: **http://167.233.102.255:8080** · Performer console: **/admin** · Health: **/healthz**

## Ports on the shared box

| Port | Owner | Notes |
|------|-------|-------|
| 80 / 443 | CityLeaks nginx | default server, untouched |
| 3000 | CityLeaks node | |
| **8080** | **ScrollMe nginx** | public; opened in ufw |
| **8081** | **ScrollMe app** | localhost only (PM2) |
| 9000 | (OSC) | local-only, disabled in prod |

## Files

| File | Purpose |
|------|---------|
| `ecosystem.config.cjs` | PM2 process def — runs `main.py` via the repo venv python. |
| `nginx-scrollme.conf` | Reverse proxy `:8080 → :8081` with WebSocket upgrade headers. |
| `bootstrap-app.sh` | First-time bring-up: clone, venv, PM2, nginx site, firewall. |
| `../.github/workflows/deploy.yml` | CI/CD: pull + pip + PM2 restart on push to `main`. |

## First-time setup (run once, as root on the server)

The box is already provisioned by CityLeaks (Node, PM2, nginx, ufw). ScrollMe
only needs Python's venv package, then the bootstrap:

```bash
apt-get install -y python3-venv           # or python3.14-venv on this box
curl -fsSL https://raw.githubusercontent.com/mahdiibakhshii/scrollMe/main/deploy/bootstrap-app.sh | bash
# or: git clone … /opt/scrollme && cd /opt/scrollme && bash deploy/bootstrap-app.sh
```

## Required GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions. Same VPS/key as CityLeaks:

| Secret | Value |
|--------|-------|
| `SSH_HOST` | `167.233.102.255` |
| `SSH_USER` | `root` |
| `SSH_PRIVATE_KEY` | private half of the deploy keypair (`~/.ssh/cityleaks_hetzner`) |

## Optional: protect the admin endpoint

`/admin/event` can fire arbitrary events. For a public show, require a token:

```bash
# On the server, as root:
echo 'ADMIN_TOKEN=<a-long-random-value>' >> /etc/environment
export ADMIN_TOKEN='<the-same-value>'
cd /opt/scrollme && pm2 restart scrollme --update-env && pm2 save
```

Then enter that token in the `/admin` console (or send `X-Admin-Token`).

## Adding a domain + HTTPS later

Point a DNS A record at the box, set `server_name` in `nginx-scrollme.conf`, then:

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d scrollme.example.com --agree-tos -m mhdi.bakhshii@gmail.com --redirect
```

Phones then use `https://…` and TD uses `wss://…/ws`.

## Useful server commands

```bash
pm2 status                         # process state
pm2 logs scrollme                  # live logs
pm2 restart scrollme               # manual restart
curl localhost:8081/healthz        # health + connection counts
```
