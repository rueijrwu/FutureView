#!/usr/bin/env bash
set -euo pipefail

ROOT=${1:-../runtime/cloud-export}
BUCKET=${MES_REPLAY_R2_BUCKET:-futureview-data}
PREFIX=mes-replay/v1

if [[ ! -f "$ROOT/manifest.json" ]]; then
  echo "Missing $ROOT/manifest.json" >&2
  exit 1
fi

put() {
  local file=$1
  local rel=${file#"$ROOT"/}
  local key="$PREFIX/$rel"
  echo "R2 PUT $key"
  npx --yes wrangler@4.125.0 r2 object put "$BUCKET/$key" --file "$file" --remote
}

put "$ROOT/manifest.json"
while IFS= read -r -d '' file; do put "$file"; done < <(find "$ROOT/contracts" -type f -name '*.json.gz' -print0 | sort -z)
