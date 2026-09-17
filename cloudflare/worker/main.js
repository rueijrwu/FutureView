const PAGES_ORIGIN = "https://futureview.pages.dev";
const DISPLAY_TIME_ZONE = "America/New_York";
const SESSION_END_HOUR_ET = 17;
const USERNAME_RE = /^[A-Za-z0-9._-]{3,32}$/;
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
const PBKDF2_ITERATIONS = 310000;
const PUBLIC_ASSETS = new Set(["/login", "/login.html", "/login.css", "/login.js", "/favicon.ico"]);
const SESSION_LIST_CACHE = new Map();

const timeFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function json(request, value, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...corsHeaders(request),
      ...extraHeaders,
    },
  });
}

function corsHeaders(request) {
  const origin = request.headers.get("origin");
  const allowed = origin === PAGES_ORIGIN ? origin : PAGES_ORIGIN;
  return {
    "access-control-allow-origin": allowed,
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type, authorization",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    vary: "Origin",
  };
}

function getCookie(request, name) {
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function authToken(request) {
  const header = request.headers.get("authorization") || "";
  if (/^Bearer\s+/i.test(header)) return header.replace(/^Bearer\s+/i, "").trim();
  const url = new URL(request.url);
  return url.searchParams.get("access_token") || getCookie(request, "fv_session");
}

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomToken(bytes = 32) {
  const data = new Uint8Array(bytes);
  crypto.getRandomValues(data);
  return base64Url(data);
}

function utf8(value) {
  return new TextEncoder().encode(value);
}

function bytesToHex(bytes) {
  return Array.from(bytes, (x) => x.toString(16).padStart(2, "0")).join("");
}

async function sha256(value) {
  return bytesToHex(new Uint8Array(await crypto.subtle.digest("SHA-256", utf8(value))));
}

async function hashPassword(password, salt = randomToken(18)) {
  const key = await crypto.subtle.importKey("raw", utf8(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: utf8(salt), iterations: PBKDF2_ITERATIONS }, key, 256);
  return { salt, hash: bytesToHex(new Uint8Array(bits)) };
}

function timingSafeEqual(a, b) {
  const aa = utf8(String(a));
  const bb = utf8(String(b));
  if (aa.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < aa.length; i += 1) diff |= aa[i] ^ bb[i];
  return diff === 0;
}

async function verifyPassword(password, salt, expected) {
  const actual = await hashPassword(password, salt);
  return timingSafeEqual(actual.hash, expected);
}

function normalizeUsername(value) {
  const username = String(value || "").trim();
  if (!USERNAME_RE.test(username)) throw new Error("Username must be 3-32 letters, numbers, dot, underscore, or dash");
  return username;
}

function validatePassword(value) {
  const password = String(value || "");
  if (password.length < 10 || password.length > 128) throw new Error("Password must be 10-128 characters");
  return password;
}

async function registrationOpen(env) {
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM app_users").first();
  return Number(row?.n || 0) === 0;
}

async function register(env, usernameValue, passwordValue) {
  const username = normalizeUsername(usernameValue);
  const password = validatePassword(passwordValue);
  if (!(await registrationOpen(env))) throw new Error("Registration is closed");
  const { salt, hash } = await hashPassword(password);
  const now = new Date().toISOString();
  const result = await env.DB.prepare(
    "INSERT INTO app_users (username, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?) RETURNING id, username"
  ).bind(username, hash, salt, now).first();
  if (!result) throw new Error("Unable to create user");
  return result;
}

async function authenticate(env, usernameValue, passwordValue) {
  let username;
  try { username = normalizeUsername(usernameValue); } catch { return null; }
  const password = String(passwordValue || "");
  const row = await env.DB.prepare("SELECT id, username, password_hash, password_salt FROM app_users WHERE username = ?").bind(username).first();
  if (!row) return null;
  return (await verifyPassword(password, row.password_salt, row.password_hash)) ? row : null;
}

async function createAuthSession(env, userId) {
  const token = randomToken(36);
  const tokenHash = await sha256(token);
  const now = new Date();
  const expiresAt = new Date(now.getTime() + SESSION_TTL_SECONDS * 1000);
  await env.DB.prepare(
    "INSERT INTO app_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(tokenHash, userId, now.toISOString(), expiresAt.toISOString()).run();
  return {
    token,
    expiresAt: expiresAt.toISOString(),
    cookie: `fv_session=${encodeURIComponent(token)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_TTL_SECONDS}`,
  };
}

async function purgeExpiredSessions(env) {
  await env.DB.prepare("DELETE FROM app_sessions WHERE expires_at <= ?").bind(new Date().toISOString()).run();
}

async function currentUser(request, env) {
  const token = authToken(request);
  if (!token) return null;
  const tokenHash = await sha256(token);
  return env.DB.prepare(`
    SELECT u.id, u.username
    FROM app_sessions s JOIN app_users u ON u.id = s.user_id
    WHERE s.token_hash = ? AND s.expires_at > ?
  `).bind(tokenHash, new Date().toISOString()).first();
}

async function destroySession(request, env) {
  const token = authToken(request);
  if (token) await env.DB.prepare("DELETE FROM app_sessions WHERE token_hash = ?").bind(await sha256(token)).run();
  return "fv_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0";
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

async function readManifest(env, product = "MES") {
  const key = `${String(product).toLowerCase()}-replay/v1/manifest.json`;
  const object = await env.MES_DATA.get(key);
  return object ? object.json() : null;
}

function zonedParts(date) {
  return Object.fromEntries(timeFormatter.formatToParts(date).filter((p) => p.type !== "literal").map((p) => [p.type, Number(p.value)]));
}

function sessionDateFromEpoch(seconds) {
  const p = zonedParts(new Date(seconds * 1000));
  const d = new Date(Date.UTC(p.year, p.month - 1, p.day));
  if (p.hour >= SESSION_END_HOUR_ET) d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function resolveContract(manifest, product, startValue) {
  const start = Math.floor(new Date(startValue).getTime() / 1000);
  if (!Number.isFinite(start)) throw new Error("Invalid start timestamp");
  const target = sessionDateFromEpoch(start);
  const volumes = manifest.contract_selection?.session_volumes ?? {};
  const sessions = Object.keys(volumes).filter((x) => x < target).sort();
  const sourceSession = sessions.at(-1) ?? null;
  let candidates = [];
  if (sourceSession) {
    candidates = Object.entries(volumes[sourceSession] ?? {}).filter(([contract]) => manifest.contracts?.[contract]);
    candidates.sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0]));
  }
  let contract = candidates[0]?.[0] ?? null;
  let reason = sourceSession ? "prior_session_max_volume" : "no_prior_session_fallback";
  if (!contract) {
    const available = Object.values(manifest.contracts ?? {}).filter((x) => Number(x.first_time) <= start && Number(x.last_time) >= start);
    available.sort((a, b) => Number(a.first_time) - Number(b.first_time) || String(a.contract).localeCompare(String(b.contract)));
    contract = available[0]?.contract ?? null;
  }
  if (!contract) throw new Error(`No ${product} contract is available for requested start`);
  return { contract, rule: "runtime_prior_session_max_volume", source_session: sourceSession, reason };
}

function metadataSessions(manifest) {
  const selection = manifest?.contract_selection ?? {};
  const explicit = Array.isArray(selection.sessions) ? selection.sessions : [];
  const values = explicit
    .map((item) => typeof item === "string" ? item : item?.session)
    .filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(String(item)));
  if (values.length) return [...new Set(values)].sort();

  const volumeSessions = Object.keys(selection.session_volumes ?? {})
    .filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(item));
  if (volumeSessions.length) return [...new Set(volumeSessions)].sort();

  const legacy = Array.isArray(selection.calendar) ? selection.calendar : [];
  const legacyValues = legacy
    .map((item) => item?.session)
    .filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(String(item)));
  if (legacyValues.length) return [...new Set(legacyValues)].sort();

  const topLevel = Array.isArray(manifest?.sessions) ? manifest.sessions : [];
  return [...new Set(
    topLevel.map((item) => typeof item === "string" ? item : item?.session)
      .filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(String(item)))
  )].sort();
}

async function manifestSessions(env, manifest, product) {
  const metadata = metadataSessions(manifest);
  if (metadata.length) return metadata;

  const contracts = Object.values(manifest?.contracts ?? {});
  const first = Math.min(...contracts.map((item) => Number(item.first_time)).filter(Number.isFinite));
  const last = Math.max(...contracts.map((item) => Number(item.last_time)).filter(Number.isFinite));
  const cacheKey = `${String(product).toUpperCase()}:${manifest?.version ?? "legacy"}:${contracts.length}:${first}:${last}`;
  if (SESSION_LIST_CACHE.has(cacheKey)) return SESSION_LIST_CACHE.get(cacheKey);

  const prefix = `${String(product).toLowerCase()}-replay/v1`;
  const dates = new Set();
  for (const contract of contracts) {
    const dailyShards = contract?.display_shards?.["1D"] ?? [];
    for (const meta of dailyShards) {
      if (!meta?.key) continue;
      const object = await env.MES_DATA.get(`${prefix}/${meta.key}`);
      if (!object) continue;
      const stream = String(meta.key).endsWith(".gz")
        ? object.body.pipeThrough(new DecompressionStream("gzip"))
        : object.body;
      let bars;
      try {
        bars = JSON.parse(await new Response(stream).text());
      } catch {
        continue;
      }
      for (const bar of bars || []) {
        const timestamp = Number(bar?.t);
        if (!Number.isFinite(timestamp)) continue;
        // Both legacy 00:00-UTC and corrected 00:00-ET daily stamps preserve
        // the intended trading-day date in their UTC Y/M/D fields.
        dates.add(new Date(timestamp * 1000).toISOString().slice(0, 10));
      }
    }
  }

  const sessions = [...dates].sort();
  if (sessions.length) SESSION_LIST_CACHE.set(cacheKey, sessions);
  return sessions;
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
      const sessions = await manifestSessions(env, manifest, product);
      if (!sessions.length) return json(request, { error: "Replay session metadata is unavailable" }, 503);
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
            user_id: Number(user.id),
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
      const headers = new Headers(request.headers);
      headers.set("x-futureview-user-id", String(user.id));
      return stub.fetch(new Request(request.url, { method: request.method, headers }));
    }

    return env.ASSETS.fetch(request);
  },
};