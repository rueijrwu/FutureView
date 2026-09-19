import {
  authenticate,
  createSession as createAuthSession,
  currentUser,
  destroySession,
  purgeExpiredSessions,
  register,
  registrationOpen,
} from "./auth.js";

const PAGES_ORIGIN = "https://futureview.pages.dev";
const DISPLAY_TIME_ZONE = "America/New_York";
// 17, not 18, and deliberately so. This mirrors resolver.py's
// requested_session_date, NOT its session_date. The two answer different
// questions and Python defines a separate constant for each:
//
//   session_date (SESSION_ROLL_HOUR_ET = 18)
//     "which trading session does this bar belong to?"  -> the 18:00 ET roll,
//     the hard invariant, and what builds the manifest's session list.
//
//   requested_session_date (SESSION_END_HOUR_ET = 17)
//     "given a requested start time, what is the first session that can hold a
//     bar at or after it?"
//
// CME equity-index futures halt 17:00-18:00 ET daily, so a request at 17:30 has
// no bar left in the current session and must resolve to the next one. Raising
// this to 18 would make any 17:00-17:59 ET start resolve to the session that has
// already ended, and resolveContract would then pick the contract from the wrong
// prior session. replay-session-boundary.test.mjs pins this against Python.
const REQUESTED_SESSION_END_HOUR_ET = 17;
const EXPIRY_HOUR_ET = 9;
const EXPIRY_MINUTE_ET = 30;
const MONTH_NUMBER = Object.fromEntries([..."FGHJKMNQUVXZ"].map((code, index) => [code, index + 1]));
const CONTRACT_RE = /^(.+?)([FGHJKMNQUVXZ])(\d{1,2})$/;
const PUBLIC_ASSETS = new Set(["/login", "/login.html", "/auth.js", "/auth.css"]);

const sessionFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
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

function localParts(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error("Invalid start timestamp");
  const parts = Object.fromEntries(
    sessionFormatter.formatToParts(date).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]),
  );
  return {
    year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
    hour: Number(parts.hour), minute: Number(parts.minute),
  };
}

function tradingSessionDate(value) {
  const parts = localParts(value);
  const localDate = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour >= REQUESTED_SESSION_END_HOUR_ET) localDate.setUTCDate(localDate.getUTCDate() + 1);
  return localDate.toISOString().slice(0, 10);
}

function contractExpiry(contract, referenceYear) {
  const match = CONTRACT_RE.exec(contract);
  if (!match) throw new Error(`Unsupported outright futures symbol ${contract}`);
  const month = MONTH_NUMBER[match[2]];
  const digits = match[3];
  let year;
  if (digits.length === 2) year = 2000 + Number(digits);
  else {
    const digit = Number(digits);
    const candidates = [];
    for (let y = referenceYear - 1; y < referenceYear + 10; y += 1) if (y % 10 === digit) candidates.push(y);
    year = candidates.sort((a, b) => Math.abs(a - referenceYear) - Math.abs(b - referenceYear))[0];
  }
  const first = new Date(Date.UTC(year, month - 1, 1));
  const firstFriday = 1 + (5 - first.getUTCDay() + 7) % 7;
  return { year, month, day: firstFriday + 14, hour: EXPIRY_HOUR_ET, minute: EXPIRY_MINUTE_ET };
}

function compareLocal(a, b) {
  for (const key of ["year", "month", "day", "hour", "minute"]) {
    if (a[key] !== b[key]) return a[key] - b[key];
  }
  return 0;
}

function isExpiredAt(contract, start) {
  const local = localParts(start);
  return compareLocal(local, contractExpiry(contract, local.year)) >= 0;
}

function expiryLabel(contract, referenceYear) {
  const x = contractExpiry(contract, referenceYear);
  const pad = (n) => String(n).padStart(2, "0");
  return `${x.year}-${pad(x.month)}-${pad(x.day)}T${pad(x.hour)}:${pad(x.minute)} America/New_York`;
}

function resolveContract(manifest, product, start) {
  if (String(product ?? "").toUpperCase() !== String(manifest.product ?? "").toUpperCase()) {
    throw new Error(`Unknown product ${product}`);
  }
  const meta = manifest.contract_selection ?? {};
  const sessionVolumes = meta.session_volumes;
  const sessions = Array.isArray(meta.sessions)
    ? meta.sessions.map((x) => typeof x === "string" ? x : x?.session).filter(Boolean).sort()
    : Object.keys(sessionVolumes ?? {}).sort();
  if (!sessions.length) throw new Error("Replay session metadata is unavailable");

  const target = tradingSessionDate(start);
  const sessionIndex = sessions.findIndex((session) => String(session) >= target);
  if (sessionIndex < 0) throw new Error("No replay session exists at or after requested start");
  const resolvedSession = sessions[sessionIndex];

  if (sessionVolumes && typeof sessionVolumes === "object") {
    const sourceSession = sessionIndex > 0 ? sessions[sessionIndex - 1] : null;
    const allContracts = Object.keys(manifest.contracts ?? {});
    if (sourceSession) {
      const prior = sessionVolumes[sourceSession] ?? {};
      const candidates = Object.entries(prior)
        .map(([contract, volume]) => [contract, Number(volume)])
        .filter(([contract, volume]) => manifest.contracts?.[contract] && Number.isFinite(volume) && volume > 0 && !isExpiredAt(contract, start))
        .sort((a, b) => b[1] - a[1]);
      if (candidates.length) {
        const [contract, sourceVolume] = candidates[0];
        return {
          session: resolvedSession,
          contract,
          reason: "prior_session_max_volume",
          source_session: sourceSession,
          source_volume: sourceVolume,
          candidate_volumes: Object.fromEntries(candidates),
          expiry_cutoff_et: expiryLabel(contract, Number(resolvedSession.slice(0, 4))),
        };
      }
    }
    const valid = allContracts.filter((contract) => !isExpiredAt(contract, start));
    if (!valid.length) throw new Error("No non-expired replay contract is available");
    valid.sort((a, b) => {
      const ea = contractExpiry(a, Number(resolvedSession.slice(0, 4)));
      const eb = contractExpiry(b, Number(resolvedSession.slice(0, 4)));
      return compareLocal(ea, eb);
    });
    const contract = valid[0];
    return {
      session: resolvedSession,
      contract,
      reason: "nearest_expiry_fallback",
      source_session: sessionIndex > 0 ? sessions[sessionIndex - 1] : null,
      source_volume: null,
      candidate_volumes: {},
      expiry_cutoff_et: expiryLabel(contract, Number(resolvedSession.slice(0, 4))),
    };
  }

  const legacy = (meta.sessions ?? []).find((item) => String(item.session) >= target);
  if (!legacy) throw new Error("Replay contract-selection metadata is unavailable; republish replay data version 4");
  if (!manifest.contracts?.[legacy.contract]) throw new Error(`Resolved contract ${legacy.contract} is unavailable`);
  return { ...legacy, reason: `legacy_${legacy.reason ?? "precomputed"}` };
}

function corsHeaders(request) {
  const origin = request.headers.get("origin");
  if (origin !== PAGES_ORIGIN) return {};
  return {
    "access-control-allow-origin": PAGES_ORIGIN,
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type,authorization",
    "access-control-allow-credentials": "true",
    "access-control-max-age": "86400",
    "vary": "Origin",
  };
}

function json(request, payload, status = 200, headers = {}) {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store", ...corsHeaders(request), ...headers },
  });
}

function redirect(location, headers = {}) {
  return new Response(null, { status: 303, headers: { location, "cache-control": "no-store", ...headers } });
}

function trustedAuthOrigin(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  return origin === new URL(request.url).origin || origin === PAGES_ORIGIN;
}

async function authRoutes(request, env, url) {
  if (url.pathname === "/api/auth/status" && request.method === "GET") {
    return json(request, { registration_open: await registrationOpen(env) });
  }
  if (url.pathname === "/api/auth/register" && request.method === "POST") {
    if (!trustedAuthOrigin(request)) return json(request, { error: "Origin is not allowed" }, 403);
    try {
      const body = await request.json();
      const user = await register(env, body.username, body.password);
      const session = await createAuthSession(env, user.id);
      return json(request, { ok: true, user: { username: user.username }, token: session.token, expires_at: session.expiresAt }, 201, { "set-cookie": session.cookie });
    } catch (error) {
      return json(request, { error: String(error?.message ?? error) }, 400);
    }
  }
  if (url.pathname === "/api/auth/login" && request.method === "POST") {
    if (!trustedAuthOrigin(request)) return json(request, { error: "Origin is not allowed" }, 403);
    const body = await request.json().catch(() => ({}));
    const user = await authenticate(env, body.username, body.password);
    if (!user) return json(request, { error: "Invalid username or password" }, 401);
    await purgeExpiredSessions(env);
    const session = await createAuthSession(env, user.id);
    return json(request, { ok: true, user: { username: user.username }, token: session.token, expires_at: session.expiresAt }, 200, { "set-cookie": session.cookie });
  }
  if (url.pathname === "/api/auth/logout" && request.method === "POST") {
    if (!trustedAuthOrigin(request)) return json(request, { error: "Origin is not allowed" }, 403);
    const cookie = await destroySession(request, env);
    return json(request, { ok: true }, 200, { "set-cookie": cookie });
  }
  if (url.pathname === "/api/auth/me" && request.method === "GET") {
    const user = await currentUser(request, env);
    return user ? json(request, { user: { username: user.username } }) : json(request, { error: "Unauthorized" }, 401);
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    const publicAuthResponse = await authRoutes(request, env, url);
    if (publicAuthResponse) return publicAuthResponse;

    if (PUBLIC_ASSETS.has(url.pathname)) {
      if (url.pathname === "/login") return env.ASSETS.fetch(new Request(new URL("/login.html", url), request));
      const user = await currentUser(request, env);
      if (user && (url.pathname === "/login" || url.pathname === "/login.html")) return redirect("/");
      return env.ASSETS.fetch(request);
    }

    const user = await currentUser(request, env);
    if (!user) {
      if (url.pathname.startsWith("/api/")) return json(request, { error: "Unauthorized" }, 401);
      return redirect("/login");
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
        manifest_version: manifest?.version ?? null,
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
      const rawSessions = manifest.contract_selection?.sessions ?? [];
      const sessions = rawSessions.map((x) => typeof x === "string" ? x : x?.session).filter(Boolean).sort();
      return json(request, {
        product: manifest.product ?? null,
        first_time: Math.min(...contracts.map((item) => Number(item.first_time))),
        last_time: Math.max(...contracts.map((item) => Number(item.last_time))),
        sessions,
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
            product,
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
