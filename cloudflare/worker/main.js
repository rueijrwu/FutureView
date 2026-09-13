import { ReplaySession } from "./replay-session.js";

export { ReplaySession };

// Existing production shard namespace is retained for compatibility during the
// raw-data migration. It is data layout, not the platform/package identity.

const PAGES_ORIGIN = "https://futureview.pages.dev";
const DISPLAY_TIME_ZONE = "America/New_York";
const SESSION_END_HOUR_ET = 17;
const sessionFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  hourCycle: "h23",
});

async function readManifest(env, product = "MES") {
  const prefix = `${product.toLowerCase()}-replay/v1`;
  const object = await env.MES_DATA.get(`${prefix}/manifest.json`);
  if (!object) return null;
  const manifest = JSON.parse(await object.text());
  manifest.product = manifest.product || product.toUpperCase();
  return manifest;
}

function tradingSessionDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error("Invalid start timestamp");
  const parts = Object.fromEntries(
    sessionFormatter.formatToParts(date).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]),
  );
  const localDate = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
  if (Number(parts.hour) >= SESSION_END_HOUR_ET) localDate.setUTCDate(localDate.getUTCDate() + 1);
  return localDate.toISOString().slice(0, 10);
}

function resolveContract(manifest, product, start) {
  if (String(product ?? "").toUpperCase() !== String(manifest.product ?? "").toUpperCase()) {
    throw new Error(`Unknown product ${product}`);
  }
  const sessions = manifest.contract_selection?.sessions;
  if (!Array.isArray(sessions) || !sessions.length) {
    throw new Error("Replay contract-selection metadata is unavailable; publish replay data version 3");
  }
  const target = tradingSessionDate(start);
  const selection = sessions.find((item) => String(item.session) >= target);
  if (!selection) throw new Error("No replay session exists at or after requested start");
  if (!manifest.contracts?.[selection.contract]) throw new Error(`Resolved contract ${selection.contract} is unavailable`);
  return selection;
}

function corsHeaders(request) {
  const origin = request.headers.get("origin");
  if (origin !== PAGES_ORIGIN) return {};
  return {
    "access-control-allow-origin": PAGES_ORIGIN,
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
    "vary": "Origin",
  };
}

function json(request, payload, status = 200) {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store", ...corsHeaders(request) },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    if (url.pathname === "/api/health") {
      const product = url.searchParams.get("product") || "MES";
      const manifest = await readManifest(env, product);
      return json(request, {
        service: "futureview-replay",
        product: manifest?.product ?? null,
        status: manifest ? "ok" : "data-unavailable",
        storage: "r2",
        sessions: "durable-objects",
        history: "d1",
        contracts: manifest ? Object.keys(manifest.contracts ?? {}).length : 0,
      }, manifest ? 200 : 503);
    }

    if (url.pathname === "/api/contracts") {
      const product = url.searchParams.get("product") || "MES";
      const manifest = await readManifest(env, product);
      if (!manifest) return json(request, { error: "Replay manifest not published" }, 503);
      return json(request, { product: manifest.product ?? null, contracts: Object.values(manifest.contracts ?? {}) });
    }

    if (url.pathname === "/api/replay/range" && request.method === "GET") {
      const product = url.searchParams.get("product") || "MES";
      const manifest = await readManifest(env, product);
      if (!manifest) return json(request, { error: "Replay manifest not published" }, 503);
      const contracts = Object.values(manifest.contracts ?? {});
      if (!contracts.length) return json(request, { error: "No replay contracts published" }, 503);
      return json(request, {
        product: manifest.product ?? null,
        first_time: Math.min(...contracts.map((item) => Number(item.first_time))),
        last_time: Math.max(...contracts.map((item) => Number(item.last_time))),
        selection_rule: manifest.contract_selection?.rule ?? null,
      });
    }

    const contractMatch = url.pathname.match(/^\/api\/contracts\/([^/]+)$/);
    if (contractMatch && request.method === "GET") {
      const product = url.searchParams.get("product") || "MES";
      const manifest = await readManifest(env, product);
      const contract = decodeURIComponent(contractMatch[1]);
      const info = manifest?.contracts?.[contract];
      return info ? json(request, info) : json(request, { error: `Unknown contract ${contract}` }, 404);
    }

    if (url.pathname === "/api/replay/sessions" && request.method === "POST") {
      try {
        const body = await request.json();
        const product = body.product || "MES";
        const manifest = await readManifest(env, product);
        if (!manifest) return json(request, { error: "Replay manifest not published" }, 503);
        const selection = resolveContract(manifest, product, body.start);
        const id = crypto.randomUUID();
        const stub = env.REPLAY_SESSION.get(env.REPLAY_SESSION.idFromName(id));
        const response = await stub.fetch("https://session/init", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            session_id: id,
            product: product,
            contract: selection.contract,
            contract_selection: selection,
            start: body.start,
            warmup: body.warmup ?? 300,
          }),
        });
        const payload = await response.json();
        if (!response.ok) return json(request, payload, response.status);
        return json(request, { ...payload, session_id: id, websocket: `/api/replay/sessions/${id}/ws` }, 201);
      } catch (error) {
        return json(request, { error: String(error?.message ?? error) }, 400);
      }
    }

    const sessionMatch = url.pathname.match(/^\/api\/replay\/sessions\/([0-9a-f-]+)\/ws$/i);
    if (sessionMatch) {
      const id = sessionMatch[1];
      const stub = env.REPLAY_SESSION.get(env.REPLAY_SESSION.idFromName(id));
      return stub.fetch(request);
    }

    return env.ASSETS.fetch(request);
  },
};
