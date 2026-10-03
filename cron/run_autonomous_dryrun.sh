#!/bin/bash
# Wrapper to source .env before running autonomous_dryrun.py
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
set -a
source "$PROJECT_DIR/.env"
set +a
exec python3 "$PROJECT_DIR/autonomous_dryrun.py" "$@"
