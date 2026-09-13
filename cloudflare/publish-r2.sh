#!/usr/bin/env bash
set -euo pipefail

ROOT=${1:-../runtime/cloud-export}
BUCKET=${MES_REPLAY_R2_BUCKET:-futureview-data}
PREFIX=${REPLAY_PREFIX:-mes-replay/v1}
PARALLELISM=${R2_PUBLISH_PARALLELISM:-12}

if [[ ! -f "$ROOT/manifest.json" ]]; then
  echo "Missing $ROOT/manifest.json" >&2
  exit 1
fi

if ! [[ "$PARALLELISM" =~ ^[1-9][0-9]*$ ]]; then
  echo "R2_PUBLISH_PARALLELISM must be a positive integer" >&2
  exit 1
fi

put() {
  local file=$1
  local rel=${file#"$ROOT"/}
  local key="$PREFIX/$rel"
  echo "R2 PUT $key"
  npx --yes wrangler@4.125.0 r2 object put "$BUCKET/$key" --file "$file" --remote
}
export -f put
export ROOT BUCKET PREFIX

# Publish shards concurrently; publish manifest last so readers only observe a
# manifest after all referenced shard objects have completed successfully.
find "$ROOT/contracts" -type f -name '*.json.gz' -print0 \
  | sort -z \
  | xargs -0 -r -n 1 -P "$PARALLELISM" bash -c 'put "$1"' _

put "$ROOT/manifest.json"
