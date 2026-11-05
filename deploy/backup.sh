#!/usr/bin/env bash
# Sao lưu PostgreSQL hằng ngày (cron trên EC2), giữ 14 bản gần nhất.
#   0 3 * * * /home/ubuntu/greenhub/deploy/backup.sh >> /home/ubuntu/greenhub/backups/backup.log 2>&1
# Kéo về laptop: scp ubuntu@<host>:greenhub/backups/*.sql.gz ./backups/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/backups"
KEEP=14
mkdir -p "$OUT"

# shellcheck disable=SC1091
set -a; . "$ROOT/.env"; set +a

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T timescaledb \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT/greenhub_$STAMP.dump"

ls -1t "$OUT"/greenhub_*.dump | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "[backup] $OUT/greenhub_$STAMP.dump"

