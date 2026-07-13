#!/usr/bin/env bash
# First-time bring-up of ScrollMe on the (already-provisioned) CityLeaks box.
# Idempotent — safe to re-run. Routine updates afterwards are handled by
# .github/workflows/deploy.yml. Run as root on the server:
#     curl -fsSL <raw bootstrap url> | bash      # or copy + bash bootstrap-app.sh
set -euo pipefail

REPO=https://github.com/mahdiibakhshii/scrollMe.git
APP=/opt/scrollme
PORT_PUBLIC=8080

echo "[1/6] clone / update repo"
if [ -d "$APP/.git" ]; then
  cd "$APP"; git fetch --depth=1 origin main; git reset --hard origin/main
else
  git clone --depth=1 "$REPO" "$APP"
fi
cd "$APP"

echo "[2/6] python venv + deps (needs python3 + python3-venv, present on the box)"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "[3/6] start / restart under PM2"
pm2 start deploy/ecosystem.config.cjs --update-env || pm2 restart scrollme --update-env
pm2 save

echo "[4/6] enable PM2 on boot (no-op if CityLeaks already set it up)"
env PATH="$PATH:/usr/local/bin" pm2 startup systemd -u root --hp /root | tail -1 | bash || true
pm2 save

echo "[5/6] nginx reverse proxy on :$PORT_PUBLIC (leaves CityLeaks' :80/:443 untouched)"
cp deploy/nginx-scrollme.conf /etc/nginx/sites-available/scrollme
ln -sf /etc/nginx/sites-available/scrollme /etc/nginx/sites-enabled/scrollme
nginx -t && systemctl reload nginx

echo "[6/6] firewall: open :$PORT_PUBLIC"
ufw allow ${PORT_PUBLIC}/tcp

echo "BOOTSTRAP_DONE — http://\$(curl -s ifconfig.me):$PORT_PUBLIC"
