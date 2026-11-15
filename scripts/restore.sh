#!/bin/sh
# Restore into a NEW, empty installation, never overwrite a running database.
set -eu
umask 077
cd "$(dirname "$0")/.."
backup_dir="${1:?Usage: sh scripts/restore.sh /absolute/path/to/backup}"
case "$backup_dir" in /*) ;; *) echo 'Use an absolute backup directory' >&2; exit 1;; esac
test ! -e .env || { echo '.env exists. Restore only into a fresh checkout/installation.' >&2; exit 1; }
( cd "$backup_dir" && shasum -a 256 -c SHA256SUMS )
grep -qx 'Open-CCAI backup format 1' "$backup_dir/FORMAT"
cp "$backup_dir/environment.env" .env
chmod 600 .env
docker compose up -d --wait db rabbit
# Refuse an existing database; PostgreSQL system schemas do not count.
table_count=$(docker compose exec -T db psql -U ccai -d ccai -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "$table_count" = 0 ] || { echo 'Database is not empty; restore refused.' >&2; exit 1; }
docker compose exec -T db pg_restore -U ccai -d ccai --exit-on-error < "$backup_dir/database.dump"
docker compose run --rm --no-deps -T api tar -C /data/uploads -xf - < "$backup_dir/uploads.tar"
docker compose up -d --build
echo 'Restore complete. Verify health, document retrieval, login, and conversation history.'
