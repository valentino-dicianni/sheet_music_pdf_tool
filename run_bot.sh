#!/usr/bin/env bash
# Build and (re)start the Telegram bot container.
#   ./run_bot.sh          rebuild the image and restart the bot
#   ./run_bot.sh logs     follow the logs
#   ./run_bot.sh stop     stop and remove the container
set -euo pipefail
cd "$(dirname "$0")"

NAME=sheetbot

case "${1:-start}" in
  start)
    [ -f .env ] || { echo "error: .env not found (cp .env.example .env and set TELEGRAM_BOT_TOKEN)" >&2; exit 1; }
    docker build -t "$NAME" .
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" --restart unless-stopped --env-file .env "$NAME"
    echo "bot started; follow logs with: ./run_bot.sh logs"
    ;;
  logs) docker logs -f "$NAME" ;;
  stop) docker rm -f "$NAME" ;;
  *) echo "usage: $0 [start|logs|stop]" >&2; exit 1 ;;
esac
