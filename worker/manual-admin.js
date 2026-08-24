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

export async function maybeHandleManualAdmin(request, env) {
  const url = new URL(request.url);
  if (url.pathname !== "/api/admin/refresh-universe") return null;

  if (request.method !== "POST") {
    return Response.json({ error: "method not allowed" }, {
      status: 405,
      headers: { allow: "POST" },
    });
  }

  if (!env.ADMIN_TOKEN) {
    return Response.json({ error: "ADMIN_TOKEN Worker secret is not configured" }, { status: 503 });
  }

  const supplied = bearerToken(request);
  if (!supplied || supplied !== env.ADMIN_TOKEN) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const requestedDate = url.searchParams.get("date");
  const targetDate = requestedDate ?? newYorkDateNow();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
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
