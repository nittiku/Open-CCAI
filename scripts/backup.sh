#!/bin/sh
# Quiesce writers for a consistent PostgreSQL + document-files backup.
set -eu
umask 077
cd "$(dirname "$0")/.."
backup_dir="${1:?Usage: sh scripts/backup.sh /absolute/path/to/new-backup-directory}"
case "$backup_dir" in /*) ;; *) echo 'Use an absolute backup directory' >&2; exit 1;; esac
mkdir "$backup_dir"
resume() { docker compose start api worker scheduler >/dev/null; }
trap resume EXIT INT TERM
docker compose stop api worker scheduler
docker compose exec -T db pg_dump -U ccai -d ccai -Fc > "$backup_dir/database.dump"
# A throwaway container mounts the exact same named uploads volume.
docker compose run --rm --no-deps -T api tar -C /data/uploads -cf - . > "$backup_dir/uploads.tar"
cp .env "$backup_dir/environment.env"
printf 'Open-CCAI backup format 1\n' > "$backup_dir/FORMAT"
( cd "$backup_dir" && shasum -a 256 database.dump uploads.tar environment.env FORMAT > SHA256SUMS )
echo 'Backup complete. Keep the directory private: it includes encryption keys and customer data.'
