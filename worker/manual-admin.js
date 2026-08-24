import { writeDailySession } from "./daily-ingest.js";
import { refreshCommonStockUniverse } from "./universe.js";

const FEATURE_STATE_METADATA_KEY = "metadata/latest-feature-state.json";
const UNIVERSE_METADATA_KEY = "metadata/latest-common-stock-universe.json";

function newYorkDateNow() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function bearerToken(request) {
  const header = request.headers.get("authorization") ?? "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  return match ? match[1] : null;
}

async function readJsonOrNull(bucket, key) {
  const object = await bucket.get(key);
  return object ? object.json() : null;
}

async function latestUniverseMetadata(env) {
  return readJsonOrNull(env.RESEARCH, UNIVERSE_METADATA_KEY);
}

function authorizeAdmin(request, env) {
  if (!env.ADMIN_TOKEN) {
    return Response.json({ error: "ADMIN_TOKEN Worker secret is not configured" }, { status: 503 });
  }

  const supplied = bearerToken(request);
  if (!supplied || supplied !== env.ADMIN_TOKEN) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  return null;
}

function validateDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

async function requireCanonicalFeatureState(env) {
  const metadata = await readJsonOrNull(env.RESEARCH, FEATURE_STATE_METADATA_KEY);
  if (!metadata) throw new Error("canonical Cloudflare feature state is missing");
  if (!String(metadata.producer ?? "").startsWith("cloudflare")) {
    throw new Error("feature state is not canonical Cloudflare state");
  }
  return metadata;
}

function methodNotAllowed() {
  return Response.json({ error: "method not allowed" }, {
    status: 405,
    headers: { allow: "POST" },
  });
}

async function handleRefreshUniverse(url, env) {
  const requestedDate = url.searchParams.get("date");
  const targetDate = requestedDate ?? newYorkDateNow();
  if (!validateDate(targetDate)) {
    return Response.json({ error: "date must be YYYY-MM-DD" }, { status: 400 });
  }

  const before = await latestUniverseMetadata(env);
  const refreshed = await refreshCommonStockUniverse(env, targetDate);
  const after = await latestUniverseMetadata(env);

  return Response.json({
    status: "complete",
    action: "refresh-universe",
    target_date: targetDate,
    before,
    result: refreshed,
    after,
  }, {
    headers: { "cache-control": "no-store" },
  });
}

async function handleRunDaily(url, env) {
  const targetDate = url.searchParams.get("date");
  if (!targetDate || !validateDate(targetDate)) {
    return Response.json({ error: "date query parameter is required as YYYY-MM-DD" }, { status: 400 });
  }

  const ingest = await writeDailySession(env, targetDate);
  const featureState = await requireCanonicalFeatureState(env);
  if (targetDate <= featureState.as_of) {
    return Response.json({
      status: "no_op",
      action: "run-daily",
      target_date: targetDate,
      reason: "target date is not newer than canonical feature state",
      ingest,
      feature_state_as_of: featureState.as_of,
    }, {
      headers: { "cache-control": "no-store" },
    });
  }

  const instance = await env.INCREMENTAL_FEATURES.create({
    params: {
      mode: "production",
      ingest_date: targetDate,
    },
  });

  return Response.json({
    status: "started",
    action: "run-daily",
    target_date: targetDate,
    ingest,
    feature_state_as_of: featureState.as_of,
    incremental_workflow_instance: instance.id,
    downstream: "incremental features -> production ranking -> replay trigger",
  }, {
    status: 202,
    headers: { "cache-control": "no-store" },
  });
}

export async function maybeHandleManualAdmin(request, env) {
  const url = new URL(request.url);
  const routes = new Set([
    "/api/admin/refresh-universe",
    "/api/admin/run-daily",
  ]);
  if (!routes.has(url.pathname)) return null;

  if (request.method !== "POST") return methodNotAllowed();

  const authError = authorizeAdmin(request, env);
  if (authError) return authError;

  try {
    if (url.pathname === "/api/admin/refresh-universe") {
      return await handleRefreshUniverse(url, env);
    }
    return await handleRunDaily(url, env);
  } catch (error) {
    console.error(`Manual admin action failed for ${url.pathname}`, error);
    return Response.json({
      status: "failed",
      action: url.pathname.split("/").at(-1),
      error: error instanceof Error ? error.message : String(error),
    }, {
      status: 500,
      headers: { "cache-control": "no-store" },
    });
  }
}
