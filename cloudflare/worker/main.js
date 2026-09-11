import { ReplaySession } from "./replay-session.js";

export { ReplaySession };

// Existing production shard namespace is retained for compatibility during the
// raw-data migration. It is data layout, not the platform/package identity.
const PREFIX = "mes-replay/v1";
const PAGES_ORIGIN = "https://futureview.pages.dev";

async function readManifest(env) {
  const object = await env.MES_DATA.get(`${PREFIX}/manifest.json`);
  if (!object) return null;
  return JSON.parse(await object.text());
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
      const manifest = await readManifest(env);
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
      const manifest = await readManifest(env);
      if (!manifest) return json(request, { error: "Replay manifest not published" }, 503);
      return json(request, { product: manifest.product ?? null, contracts: Object.values(manifest.contracts ?? {}) });
    }

    const contractMatch = url.pathname.match(/^\/api\/contracts\/([^/]+)$/);
    if (contractMatch && request.method === "GET") {
      const manifest = await readManifest(env);
      const contract = decodeURIComponent(contractMatch[1]);
      const info = manifest?.contracts?.[contract];
      return info ? json(request, info) : json(request, { error: `Unknown contract ${contract}` }, 404);
    }

    if (url.pathname === "/api/replay/sessions" && request.method === "POST") {
      const body = await request.json();
      const manifest = await readManifest(env);
      const contract = String(body.contract ?? "");
      if (!manifest?.contracts?.[contract]) return json(request, { error: `Unknown contract ${contract}` }, 400);
      const id = crypto.randomUUID();
      const stub = env.REPLAY_SESSION.get(env.REPLAY_SESSION.idFromName(id));
      const response = await stub.fetch("https://session/init", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: id, contract, start: body.start, warmup: body.warmup ?? 300 }),
      });
      const payload = await response.json();
      if (!response.ok) return json(request, payload, response.status);
      return json(request, { ...payload, session_id: id, websocket: `/api/replay/sessions/${id}/ws` }, 201);
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
