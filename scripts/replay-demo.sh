#!/usr/bin/env bash
set -euo pipefail

# Seed only synthetic dev cases and a fixed draft. Keep all SQLite state outside
# the repository so this command never reads or modifies a merchant database.
demo_dir="$(mktemp -d "${TMPDIR:-/tmp}/proof-trail-replay.XXXXXX")"
export PT_DB="$demo_dir/replay.db"
export PT_MODE=replay
export PT_ENV=development
export PT_UI_FIXTURES=1
export PT_AUTOPOLL=0
export PT_SUBMIT_MODE=dry-run
replay_port="${PT_REPLAY_PORT:-8001}"
python -m scripts.replay_seed

printf 'Offline replay mode. No model or PayPal requests are enabled.\n'
printf 'Temporary database: %s\n' "$PT_DB"
printf 'Open http://127.0.0.1:%s (Ctrl+C to stop).\n' "$replay_port"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$replay_port"
