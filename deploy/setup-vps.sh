#!/usr/bin/env bash
# One-shot VPS setup for the Prysma web dashboard.
# Run as root on the VPS:  bash setup-vps.sh
set -euo pipefail

REPO="https://github.com/driftedslinky/prysma-competitive-intel.git"
APP_DIR="/opt/prysma"
PORT=8000

echo "==> 1/6 Installing system packages"
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl ufw

echo "==> 2/6 Cloning repository"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR" && git pull --ff-only
else
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> 3/6 Creating virtualenv and installing dependencies"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> 4/6 Configuring environment"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ""
  echo "  !!  ACTION REQUIRED: edit $APP_DIR/.env and add real keys:"
  echo "      NEBIUS_API_KEY, TAVILY_API_KEY, TELEGRAM_BOT_TOKEN"
  echo "      Then re-run:  systemctl restart prysma-web"
  echo ""
fi

echo "==> 5/6 Installing systemd service"
cp "$APP_DIR/deploy/prysma-web.service" /etc/systemd/system/prysma-web.service
systemctl daemon-reload
systemctl enable prysma-web
systemctl restart prysma-web

echo "==> 6/6 Opening firewall port $PORT"
ufw allow "$PORT"/tcp || true

sleep 3
echo ""
echo "==> Status"
systemctl --no-pager status prysma-web | head -12 || true
echo ""
echo "==> Health check"
curl -s "http://127.0.0.1:$PORT/api/status" || echo "(not responding yet - check: journalctl -u prysma-web -n 50)"
echo ""
echo "Done. Public URL:  http://$(curl -s ifconfig.me):$PORT"