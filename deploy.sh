#!/usr/bin/env bash
# Деплой на боевой сервер: пуш в GitHub + пуш на сервер + пересборка контейнеров.
# Использование: ./deploy.sh [backend|frontend]  (без аргумента — пересобрать оба)
set -euo pipefail

SERVICE="${1:-}"

git push origin main
git push production main

ssh lexx@91.147.104.52 "cd ~/audit-generator && sudo docker compose up -d --build ${SERVICE}"
echo "Deployed: $(git rev-parse --short HEAD)"
