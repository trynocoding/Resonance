#!/usr/bin/env bash
set -euo pipefail

release_dir=$(cd -- "$(dirname -- "$0")" && pwd)
state_dir=${STATE_DIRECTORY:?Run with a dedicated systemd StateDirectory}
app_dir=${RESONANCE_APP_DIR:-/opt/resonance}
database=${RESONANCE_DATABASE:-/var/lib/resonance/app/etf_monitor.db}
branch=resonance-data
repo=git@github.com:trynocoding/Resonance.git

exec 9>"$state_dir/publish.lock"
flock -n 9

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
chown resonance:resonance "$scratch"
runuser -u resonance -- "$app_dir/.venv/bin/python" - "$database" "$scratch/etf_monitor.db" <<'PY'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(source, uri=True, timeout=15)) as reader:
    with closing(sqlite3.connect(sys.argv[2])) as backup:
        reader.backup(backup, pages=128, sleep=0.05)
PY
runuser -u resonance -- env ETF_MONITOR_HOME="$scratch" PYTHONPATH="$app_dir/backend" \
  "$app_dir/.venv/bin/python" "$release_dir/pages_export.py" --output "$scratch/resonance.json"

export GIT_SSH_COMMAND="ssh -i $state_dir/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$state_dir/known_hosts -o BatchMode=yes -o ConnectTimeout=15"
checkout="$state_dir/data"
if [[ ! -d "$checkout/.git" ]]; then
  git init --initial-branch="$branch" "$checkout"
  git -C "$checkout" remote add origin "$repo"
fi

remote_branch=$(git -C "$checkout" ls-remote --heads origin "refs/heads/$branch")
if [[ -n "$remote_branch" ]]; then
  git -C "$checkout" fetch --depth=1 origin "refs/heads/$branch"
  git -C "$checkout" reset --hard FETCH_HEAD
fi
install -m 0644 "$scratch/resonance.json" "$checkout/resonance.json"
git -C "$checkout" add -- resonance.json
if git -C "$checkout" diff --cached --quiet; then
  exit 0
fi
git -C "$checkout" -c user.name='Resonance Publisher' -c user.email='resonance-publisher@users.noreply.github.com' \
  commit -m "Publish Resonance market snapshot"
git -C "$checkout" push origin "HEAD:refs/heads/$branch"
