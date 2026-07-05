#!/usr/bin/env bash
# Деплой на боевой сервер: пуш в GitHub + пуш на сервер + пересборка контейнеров.
# Адрес сервера хранится в .deploy-server (в git не попадает):
#   echo "user@host" > .deploy-server
# Использование: ./deploy.sh [backend|frontend]  (без аргумента — пересобрать оба)
set -euo pipefail

SERVICE="${1:-}"
SERVER="$(cat "$(dirname "$0")/.deploy-server")"

git push origin main
git push production main

ssh "$SERVER" "cd ~/audit-generator && sudo docker compose up -d --build ${SERVICE}"
echo "Deployed: $(git rev-parse --short HEAD)"
