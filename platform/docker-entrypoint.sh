#!/bin/sh
# Entrypoint dùng chung: "api" chạy migration rồi khởi động FastAPI; "worker" chạy worker.
set -e

case "$1" in
  api)
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec python -m worker.main
    ;;
  *)
    exec "$@"
    ;;
esac

