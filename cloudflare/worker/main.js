import { ReplaySession } from "./replay-session.js";

export { ReplaySession };

const PREFIX = "mes-replay/v1";

async function readManifest(env) {
  const object = await env.MES_DATA.get(`${PREFIX}/manifest.json`);
  if (!object) return null;
  return JSON.parse(await object.text());
}

function json(payload, status = 200) {
  return Response.json(payload, { status, headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      const manifest = await readManifest(env);
      return json({
        service: "futureview-mes-replay",
        status: manifest ? "ok" : "data-unavailable",
        storage: "r2",
        sessions: "durable-objects",
        history: "d1",
        contracts: manifest ? Object.keys(manifest.contracts ?? {}).length : 0,
      }, manifest ? 200 : 503);
    }

    if (url.pathname === "/api/contracts") {
      const manifest = await readManifest(env);
      if (!manifest) return json({ error: "MES replay manifest not published" }, 503);
      return json({ contracts: Object.values(manifest.contracts ?? {}) });
    }

    const contractMatch = url.pathname.match(/^\/api\/contracts\/([^/]+)$/);
    if (contractMatch && request.method === "GET") {
      const manifest = await readManifest(env);
      const contract = decodeURIComponent(contractMatch[1]);
      const info = manifest?.contracts?.[contract];
      return info ? json(info) : json({ error: `Unknown contract ${contract}` }, 404);
    }

    if (url.pathname === "/api/replay/sessions" && request.method === "POST") {
      const body = await request.json();
      const manifest = await readManifest(env);
      const contract = String(body.contract ?? "");
      if (!manifest?.contracts?.[contract]) return json({ error: `Unknown contract ${contract}` }, 400);
      const id = crypto.randomUUID();
      const stub = env.REPLAY_SESSION.get(env.REPLAY_SESSION.idFromName(id));
      const response = await stub.fetch("https://session/init", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: id, contract, start: body.start, warmup: body.warmup ?? 300 }),
      });
      const payload = await response.json();
      if (!response.ok) return json(payload, response.status);
      return json({ ...payload, session_id: id, websocket: `/api/replay/sessions/${id}/ws` }, 201);
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
