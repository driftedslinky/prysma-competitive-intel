#!/usr/bin/env bash
# One-shot VPS setup for the Prysma web dashboard.
# Run as root on the VPS:  bash setup-vps.sh
#
# Deploys behind the existing Traefik instance at /docker/traefik.
# Requires DNS: prysma.vanillapolygons.com -> this VPS IP.
set -euo pipefail

REPO="https://github.com/driftedslinky/prysma-competitive-intel.git"
BASE="/docker/prysma"
APP="$BASE/app"

echo "==> 1/6 Cloning / updating repository"
mkdir -p "$BASE"
if [ -d "$APP/.git" ]; then
  cd "$APP" && git pull --ff-only
else
  git clone "$REPO" "$APP"
fi
cd "$APP"

echo "==> 2/6 Configuring environment"
if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"
  echo ""
  echo "  !!  ACTION REQUIRED: edit $APP/.env and add real keys:"
  echo "      NEBIUS_API_KEY, TAVILY_API_KEY, TELEGRAM_BOT_TOKEN"
  echo ""
fi

echo "==> 3/6 Building and starting the container"
cd "$APP/deploy"
docker compose up -d --build

echo "==> 4/6 Waiting for startup"
sleep 8
docker compose ps

echo "==> 5/6 Health check (local)"
container_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' prysma-web 2>/dev/null || true)
if [ -n "$container_ip" ]; then
  curl -s "http://$container_ip:8000/api/status" || echo "(not responding - check: docker logs prysma-web)"
fi

echo "==> 6/6 Done"
echo ""
echo "Public URL (once DNS resolves):  https://prysma.vanillapolygons.com"
echo "Traefik fetches the TLS certificate on the first request, so the very"
echo "first hit may fail until the cert lands. Retry after a few seconds."
echo ""
echo "Useful commands:"
echo "  docker logs -f prysma-web"
echo "  cd $APP/deploy && docker compose restart"