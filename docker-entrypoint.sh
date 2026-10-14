#!/bin/sh
# Render mounts persistent disks owned by root. Fix ownership, then drop privileges.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R 1000:1000 "$DATA_DIR" 2>/dev/null || true
    exec env HOME=/home/evaluator setpriv --reuid=1000 --regid=1000 --clear-groups "$@"
fi

exec "$@"
