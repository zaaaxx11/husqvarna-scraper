#!/usr/bin/env bash
# One full catalogue pass. Safe to re-run: --resume skips finished articles.
set -euo pipefail
APP_DIR="${APP_DIR:-/srv/husqvarna/app}"
OUT_DIR="${OUT_DIR:-/srv/husqvarna/out}"
cd "$APP_DIR"
exec .venv/bin/husqvarna-scraper all --out "$OUT_DIR" --resume --concurrency "${CONCURRENCY:-2}" --rps "${RPS:-2}"
