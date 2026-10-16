#!/usr/bin/env bash
# One-time VPS setup for ora-1 (Ubuntu 22.04, ~1GB RAM).
# Run as: bash deploy/setup-ora1.sh   (from anywhere; uses sudo)
set -euo pipefail

REPO_URL="git@github.com:rafalsza/bvt.git"
APP_DIR="$HOME/bvt"

echo "==> 1/4 Swap: bumping to ~4G total"
CURRENT_SWAP_MB=$(free -m | awk '/^Swap:/ {print $2}')
if [ "$CURRENT_SWAP_MB" -lt 4000 ]; then
  sudo swapoff -a || true
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon -a
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
free -h

echo "==> 2/4 Repo"
if [ ! -d "$APP_DIR" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

echo "==> 3/4 user_data check"
if [ ! -f "$APP_DIR/user_data/creds.yml" ]; then
  echo "!! $APP_DIR/user_data/creds.yml missing - copy it over before starting:"
  echo "   scp user_data/creds.yml ora-1:$APP_DIR/user_data/"
  echo "   (config.yml is tracked; creds.yml is NOT - never commit it)"
fi

echo "==> 4/4 Build & start"
cd "$APP_DIR"
docker compose -f deploy/docker-compose.ora1.yml up -d --build

echo "Done. Logs: docker logs -f bvt_bot"
