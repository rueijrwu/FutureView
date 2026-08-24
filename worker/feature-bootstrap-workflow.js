import { WorkflowEntrypoint } from "cloudflare:workers";

const MASSIVE_BASE_URL = "https://api.massive.com";
const STATE_VERSION = 1;
const STATE_SHARDS = 32;
const REQUIRED_SESSIONS = 211;
const LATEST_STATE_KEY = "metadata/latest-feature-state.json";
const BOOTSTRAP_STATUS_KEY = "metadata/latest-feature-bootstrap.json";
const LATEST_UNIVERSE_KEY = "metadata/latest-common-stock-universe.json";

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  if (object === null) throw new Error(`R2 object not found: ${key}`);
  return object.json();
}

async function writeJson(bucket, key, payload) {
  await bucket.put(key, JSON.stringify(payload), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
}

function shiftIsoDate(isoDate, days) {
  const date = new Date(`${isoDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isWeekend(isoDate) {
  const day = new Date(`${isoDate}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

function shardForSymbol(symbol) {
  let total = 0;
  for (const character of symbol) total += character.codePointAt(0);
  return total % STATE_SHARDS;
}

function trueRange(high, low, previousClose) {
  return Math.max(
    Number(high) - Number(low),
    Math.abs(Number(high) - Number(previousClose)),
    Math.abs(Number(low) - Number(previousClose)),
  );
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + Number(value), 0) / values.length;
}

async function fetchGroupedDaily(apiKey, tradingDate) {
  const url = new URL(
    `/v2/aggs/grouped/locale/us/market/stocks/${tradingDate}`,
    MASSIVE_BASE_URL,
  );
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", apiKey);
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "FutureView-Cloudflare/0.1",
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Massive HTTP ${response.status}: ${body.slice(0, 300)}`);
  }
  const payload = await response.json();
  const results = Array.isArray(payload.results) ? payload.results : [];
  return results
    .filter((item) => item?.T && item.o != null && item.h != null
      && item.l != null && item.c != null && item.v != null)
    .map((item) => ({
      symbol: String(item.T),
      open: Number(item.o),
      high: Number(item.h),
      low: Number(item.l),
      close: Number(item.c),
      volume: Number(item.v),
    }));
}

function buildStatesFromSessions(sessionPayloads, sourceAsOf) {
  const histories = new Map();
  for (const payload of sessionPayloads) {
    for (const bar of payload.bars ?? []) {
      const symbol = String(bar.symbol);
      let history = histories.get(symbol);
      if (!history) {
        history = {
          symbol,
          closes: [],
          highs: [],
          volumes: [],
          trueRanges: [],
          sma50History: [],
          lastDate: null,
        };
        histories.set(symbol, history);
      }

      const previousClose = history.closes.at(-1);
      if (previousClose != null) {
        history.trueRanges.push(trueRange(bar.high, bar.low, previousClose));
      }
      history.closes.push(Number(bar.close));
      history.highs.push(Number(bar.high));
      history.volumes.push(Number(bar.volume));
      if (history.closes.length >= 50) {
        history.sma50History.push(mean(history.closes.slice(-50)));
      }
      history.lastDate = payload.date;
    }
  }

  const states = [];
  for (const history of histories.values()) {
    if (
      history.closes.length < 200
      || history.highs.length < 50
      || history.volumes.length < 20
      || history.trueRanges.length < 14
      || history.sma50History.length < 11
    ) {
      continue;
    }
    states.push({
      symbol: history.symbol,
      as_of: history.lastDate ?? sourceAsOf,
      closes: history.closes.slice(-200),
      highs: history.highs.slice(-50),
      volumes: history.volumes.slice(-20),
      true_ranges: history.trueRanges.slice(-14),
      sma50_history: history.sma50History.slice(-11),
    });
  }
  states.sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));
  return states;
}

export class FeatureBootstrapWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const targetDate = String(event.payload?.target_date ?? "");
    if (!targetDate) throw new Error("feature bootstrap payload is missing target_date");
    if (!this.env.MASSIVE_API_KEY) {
      throw new Error("MASSIVE_API_KEY Worker secret is not configured");
    }

    const universe = await step.do("resolve JS common-stock universe", async () => {
      const metadata = await readJson(this.env.RESEARCH, LATEST_UNIVERSE_KEY);
      const payload = await readJson(this.env.RESEARCH, metadata.data_key);
      return {
        asOf: payload.as_of ?? metadata.as_of,
        symbols: payload.symbols ?? [],
      };
    });
    const eligible = new Set((universe.symbols ?? []).map(String));
    const workRoot = `work/feature-bootstrap/instance=${event.instanceId}`;
    const sessions = [];
    let cursor = shiftIsoDate(targetDate, -1);
    let scannedWeekdays = 0;

    while (sessions.length < REQUIRED_SESSIONS && scannedWeekdays < 320) {
      if (isWeekend(cursor)) {
        cursor = shiftIsoDate(cursor, -1);
        continue;
      }
      const date = cursor;
      scannedWeekdays += 1;
      const session = await step.do(
        `fetch bootstrap session ${date}`,
        { retries: { limit: 3, delay: "10 seconds", backoff: "exponential" }, timeout: "2 minutes" },
        async () => {
          const bars = await fetchGroupedDaily(this.env.MASSIVE_API_KEY, date);
          if (!bars.length) return { date, valid: false, shardKeys: [] };

          const shards = Array.from({ length: STATE_SHARDS }, () => []);
          for (const bar of bars) {
            if (!eligible.has(String(bar.symbol))) continue;
            shards[shardForSymbol(String(bar.symbol))].push(bar);
          }

          const shardKeys = [];
          for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
            const shardName = String(shard).padStart(2, "0");
            const key = `${workRoot}/date=${date}/shard=${shardName}.json`;
            await writeJson(this.env.RESEARCH, key, {
              date,
              shard,
              bars: shards[shard],
            });
            shardKeys.push(key);
          }
          return { date, valid: true, shardKeys };
        },
      );
      if (session.valid) sessions.push(session);
      cursor = shiftIsoDate(cursor, -1);
    }

    if (sessions.length < REQUIRED_SESSIONS) {
      throw new Error(
        `feature bootstrap found only ${sessions.length} sessions before ${targetDate}`,
      );
    }

    sessions.sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const sourceAsOf = sessions.at(-1).date;
    const stateKeys = [];
    let symbolCount = 0;

    for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
      const result = await step.do(
        `build bootstrap state shard ${String(shard).padStart(2, "0")}`,
        { retries: { limit: 2, delay: "5 seconds" }, timeout: "5 minutes" },
        async () => {
          const payloads = [];
          for (const session of sessions) {
            payloads.push(await readJson(this.env.RESEARCH, session.shardKeys[shard]));
          }
          const states = buildStatesFromSessions(payloads, sourceAsOf);
          const shardName = String(shard).padStart(2, "0");
          const key = `state/rolling/v${STATE_VERSION}/date=${sourceAsOf}/shard=${shardName}.json`;
          await writeJson(this.env.RESEARCH, key, {
            version: STATE_VERSION,
            as_of: sourceAsOf,
            shard,
            shard_count: STATE_SHARDS,
            count: states.length,
            states,
            producer: "cloudflare-js-bootstrap",
          });
          return { key, count: states.length };
        },
      );
      stateKeys.push(result.key);
      symbolCount += result.count;
    }

    const final = await step.do("promote JS feature bootstrap state", async () => {
      const now = new Date().toISOString();
      const metadata = {
        version: STATE_VERSION,
        as_of: sourceAsOf,
        shard_count: STATE_SHARDS,
        symbol_count: symbolCount,
        prefix: `state/rolling/v${STATE_VERSION}/date=${sourceAsOf}`,
        keys: stateKeys,
        producer: "cloudflare-js-bootstrap",
        workflow_instance: event.instanceId,
        universe_as_of: universe.asOf,
        bootstrap_session_count: sessions.length,
        updated_at: now,
      };
      await writeJson(
        this.env.RESEARCH,
        `state/rolling/v${STATE_VERSION}/date=${sourceAsOf}/metadata.json`,
        metadata,
      );
      await writeJson(this.env.RESEARCH, LATEST_STATE_KEY, metadata);
      await writeJson(this.env.RESEARCH, BOOTSTRAP_STATUS_KEY, {
        status: "complete",
        target_date: targetDate,
        source_as_of: sourceAsOf,
        symbol_count: symbolCount,
        session_count: sessions.length,
        workflow_instance: event.instanceId,
        updated_at: now,
      });
      return metadata;
    });

    const incremental = await step.do("start incremental pipeline after bootstrap", async () => {
      const instance = await this.env.INCREMENTAL_FEATURES.create({
        params: { mode: "production", ingest_date: targetDate },
      });
      return { id: instance.id };
    });

    return {
      status: "complete",
      target_date: targetDate,
      source_as_of: final.as_of,
      symbol_count: final.symbol_count,
      incremental_instance: incremental.id,
    };
  }
}
