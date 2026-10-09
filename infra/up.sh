#!/usr/bin/env bash
#
# Local development stack: PostgreSQL + PostGIS, pgvector, Redis, MinIO.
#
# Deliberately not required. The whole platform runs against SQLite with a
# haversine fallback and no external services, which is what makes a first run
# cheap. Bring this up when you need PostGIS `earth_distance` queries, real
# spatial clustering, or the background worker.
#
# Usage:  docker compose up -d && docker compose ps
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not on PATH."
  echo
  echo "You do not need it. The platform runs against SQLite with a haversine"
  echo "distance fallback and no external services:"
  echo
  echo "  export DATABASE_URL=sqlite:///./geothermal.db"
  echo "  python -m scripts.cli init"
  echo "  python -m scripts.cli bootstrap"
  echo "  uvicorn app.main:app --reload --app-dir backend"
  echo
  echo "Set POSTGIS when you need earth_distance queries or spatial clustering."
  exit 1
fi

exec docker compose -f "$COMPOSE_FILE" "$@"