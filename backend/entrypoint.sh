#!/usr/bin/env bash
set -e

echo "Waiting for database..."
until pg_isready -h db -p 5432 -U "${POSTGRES_USER:-gamesense}" >/dev/null 2>&1; do
  sleep 1
done
echo "Database is ready."

migrate_and_seed() {
  alembic upgrade head
  python -m app.seed
}

case "$1" in
  api)
    migrate_and_seed
    # Live reload in dev; disabled in production (compose.prod.yaml sets UVICORN_RELOAD=0).
    RELOAD_FLAG=""
    [ "${UVICORN_RELOAD:-1}" = "1" ] && RELOAD_FLAG="--reload"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 $RELOAD_FLAG
    ;;
  worker)
    exec celery -A app.tasks.celery_app.celery worker --loglevel=info
    ;;
  beat)
    exec celery -A app.tasks.celery_app.celery beat --loglevel=info
    ;;
  *)
    exec "$@"
    ;;
esac
