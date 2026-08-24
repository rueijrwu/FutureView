import fs from "node:fs/promises";
import path from "node:path";

const STATE_VERSION = 1;
const STATE_SHARDS = 32;

function validState(state) {
  return state
    && state.symbol
    && Array.isArray(state.closes) && state.closes.length >= 200
    && Array.isArray(state.highs) && state.highs.length >= 50
    && Array.isArray(state.volumes) && state.volumes.length >= 20
    && Array.isArray(state.true_ranges) && state.true_ranges.length >= 14
    && Array.isArray(state.sma50_history) && state.sma50_history.length >= 11;
}

const [sourceDir, outputDir, sourceDate] = process.argv.slice(2);
if (!sourceDir || !outputDir || !/^\d{4}-\d{2}-\d{2}$/.test(sourceDate ?? "")) {
  throw new Error("usage: node tools/recovery/state-repair.mjs <sourceDir> <outputDir> <YYYY-MM-DD>");
}

await fs.mkdir(outputDir, { recursive: true });
const keys = [];
let symbolCount = 0;
let spyFound = false;

for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
  const name = String(shard).padStart(2, "0");
  const sourcePath = path.join(sourceDir, `shard=${name}.json`);
  const payload = JSON.parse(await fs.readFile(sourcePath, "utf8"));
  const states = Array.isArray(payload.states) ? payload.states : [];
  const invalid = states.filter((state) => !validState(state));
  if (invalid.length) throw new Error(`shard ${name} contains ${invalid.length} invalid states`);
  if (states.some((state) => String(state.symbol) === "SPY")) spyFound = true;

  const canonical = {
    version: STATE_VERSION,
    as_of: sourceDate,
    shard,
    shard_count: STATE_SHARDS,
    count: states.length,
    states,
    producer: "cloudflare-js-bootstrap",
    seed_source: "github-actions-state-repair",
  };
  await fs.writeFile(path.join(outputDir, `shard=${name}.json`), JSON.stringify(canonical));
  keys.push(`state/rolling/v${STATE_VERSION}/date=${sourceDate}/shard=${name}.json`);
  symbolCount += states.length;
}

if (!spyFound) throw new Error("repaired feature state does not contain SPY benchmark state");

const now = new Date().toISOString();
const metadata = {
  version: STATE_VERSION,
  as_of: sourceDate,
  shard_count: STATE_SHARDS,
  symbol_count: symbolCount,
  prefix: `state/rolling/v${STATE_VERSION}/date=${sourceDate}`,
  keys,
  producer: "cloudflare-js-bootstrap",
  seed_source: "github-actions-state-repair",
  benchmark: "SPY",
  updated_at: now,
};
const status = {
  status: "complete",
  mode: "github-actions-state-repair",
  source_as_of: sourceDate,
  symbol_count: symbolCount,
  shard_count: STATE_SHARDS,
  benchmark: "SPY",
  updated_at: now,
};

await fs.writeFile(path.join(outputDir, "metadata.json"), JSON.stringify(metadata));
await fs.writeFile(path.join(outputDir, "status.json"), JSON.stringify(status));
console.log(JSON.stringify(status, null, 2));
