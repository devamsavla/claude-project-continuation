#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu server (Azure for Students B1s/B2ats, or any VPS).
# Usage:  curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/server/deploy/setup-server.sh | bash
# or copy this folder to the server and run:  bash deploy/setup-server.sh
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sudo sh; sudo usermod -aG docker "$USER"; fi
# 1 GB swap so small servers don't run out of memory while building
if ! swapon --show | grep -q swapfile; then sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab; fi
cd "$(dirname "$0")/.."
[ -f .env ] || { cp .env.example .env; echo ">>> Fill in .env (nano .env), then run this script again."; exit 0; }
sudo docker compose -f deploy/docker-compose.yml up -d --build
echo ">>> Mindy is starting. Check: curl https://api.whatsonyourmind.online/health"
