#!/bin/sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  echo "Usage: $0 [up|down|restart|logs|status]"
  echo "  up       Build and start all services"
  echo "  down     Stop and remove all services"
  echo "  restart  Stop then start all services"
  echo "  logs     Tail logs from all services"
  echo "  status   Show running containers"
  exit 1
}

DC="docker compose -f $DIR/docker-compose.yml --env-file $DIR/.env"

case "${1:-up}" in
  up)
    $DC up --build -d
    echo "✓ Stack started. Grafana: http://localhost:3005"
    ;;
  down)
    $DC down
    ;;
  restart)
    $DC down
    $DC up --build -d
    echo "✓ Stack restarted. Grafana: http://localhost:3005"
    ;;
  logs)
    $DC logs -f --tail=100
    ;;
  status)
    $DC ps
    ;;
  *)
    usage
    ;;
esac
