import { refreshCommonStockUniverse } from "./universe.js";

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

async function latestUniverseMetadata(env) {
  const object = await env.RESEARCH.get(UNIVERSE_METADATA_KEY);
  return object ? object.json() : null;
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

export async function maybeHandleManualAdmin(request, env) {
  const url = new URL(request.url);
  const isUniverseRefresh = url.pathname === "/api/admin/refresh-universe";
  const isFeatureBootstrap = url.pathname === "/api/admin/bootstrap-features";
  const isStateAdoption = url.pathname === "/api/admin/adopt-feature-state";
  if (!isUniverseRefresh && !isFeatureBootstrap && !isStateAdoption) return null;

  if (request.method !== "POST") {
    return Response.json({ error: "method not allowed" }, {
      status: 405,
      headers: { allow: "POST" },
    });
  }

  const authError = authorizeAdmin(request, env);
  if (authError) return authError;

  if (isStateAdoption) {
    if (!env.STATE_ADOPTION) {
      return Response.json({ error: "STATE_ADOPTION Workflow binding is not configured" }, { status: 503 });
    }

    const instance = await env.STATE_ADOPTION.create({ params: {} });
    return Response.json({
      status: "started",
      action: "adopt-feature-state",
      workflow_instance: instance.id,
    }, {
      status: 202,
      headers: { "cache-control": "no-store" },
    });
  }

  if (isFeatureBootstrap) {
    const targetDate = url.searchParams.get("date");
    if (!targetDate || !validateDate(targetDate)) {
      return Response.json({ error: "date query parameter must be YYYY-MM-DD" }, { status: 400 });
    }
    if (!env.FEATURE_BOOTSTRAP) {
      return Response.json({ error: "FEATURE_BOOTSTRAP Workflow binding is not configured" }, { status: 503 });
    }

    const instance = await env.FEATURE_BOOTSTRAP.create({
      params: { target_date: targetDate },
    });

    return Response.json({
      status: "started",
      action: "bootstrap-features",
      target_date: targetDate,
      workflow_instance: instance.id,
    }, {
      status: 202,
      headers: { "cache-control": "no-store" },
    });
  }

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
