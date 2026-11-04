#!/usr/bin/env bash
# Builds the demo platform from scratch and starts it on http://localhost:8000.
# Run from anywhere; resolves the repo root as the parent of demo_kit/.
# Delivery due times and "late" states are relative to when this script runs.
# Needs Python 3.11+ and Node 20+.
#
# Flags:
#   --keep   reuse existing LBP_DATA_DIR without wiping
#   --force  wipe even with --keep (rebuild scenario into the same dir)
#   --full   use full-scale row counts (~3k / feed)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
KEEP=0
FORCE=0
SCALE=compact
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    --force) FORCE=1 ;;
    --full) SCALE=full ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  esac
done
DATA="${DEMO_DATA_DIR:-$ROOT/.demo_data}"
PY="$ROOT/backend/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
if [ "$KEEP" -eq 0 ] && [ -d "$DATA" ]; then
  echo "Removing previous demo state in $DATA (pass --keep to reuse it)"
  rm -rf "$DATA"
fi
( cd "$ROOT/backend" && "$PY" -m pip install -q -r requirements.txt )
( cd "$ROOT/frontend" && npm ci --silent && npm run build --silent )
SETUP_ARGS=(--data-dir "$DATA" --kit "$ROOT/demo_kit" --scale "$SCALE")
if [ "$FORCE" -eq 1 ] || [ "$KEEP" -eq 0 ]; then
  SETUP_ARGS+=(--force)
fi
( cd "$ROOT/backend" && "$PY" -m lbp.cli demo-setup "${SETUP_ARGS[@]}" )
echo "Open http://localhost:8000 and use 'Signed in as' to switch persona."
echo "Live upload files: $DATA/demo_uploads/2_upload_live"
cd "$ROOT/backend" && LBP_DATA_DIR="$DATA" LBP_SCHEDULER_ENABLED=false \
  LBP_PULL_ALLOWED_HOSTS="${LBP_PULL_ALLOWED_HOSTS:-sftp.westside-partner.example}" \
  exec "$PY" -m uvicorn lbp.api.main:app --port 8000
