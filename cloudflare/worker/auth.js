const SESSION_COOKIE = "fv_session";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
const PBKDF2_ITERATIONS = 210000;
const encoder = new TextEncoder();

function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function parseCookies(header) {
  const out = {};
  for (const part of String(header || "").split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

function requestToken(request) {
  const auth = request.headers.get("authorization") || "";
  const match = /^Bearer\s+(.+)$/i.exec(auth);
  if (match) return match[1].trim();
  const cookie = parseCookies(request.headers.get("cookie"))[SESSION_COOKIE];
  if (cookie) return cookie;
  try {
    const url = new URL(request.url);
    if (/\/ws$/i.test(url.pathname)) return url.searchParams.get("access_token") || null;
  } catch {}
  return null;
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return base64url(new Uint8Array(digest));
}

async function derivePassword(password, saltBytes) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: saltBytes, iterations: PBKDF2_ITERATIONS },
    key,
    256,
  );
  return base64url(new Uint8Array(bits));
}

function decodeBase64url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

function cookieHeader(token, maxAge = SESSION_TTL_SECONDS) {
  return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${maxAge}`;
}

function clearCookieHeader() {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

export function registrationConfiguredOpen(env) {
  return String(env.REGISTRATION_OPEN ?? "true").toLowerCase() !== "false";
}

export async function accountExists(env) {
  const row = await env.DB.prepare("SELECT id FROM auth_users LIMIT 1").first();
  return Boolean(row);
}

export async function registrationOpen(env) {
  if (!registrationConfiguredOpen(env)) return false;
  return !(await accountExists(env));
}

export function validateUsername(username) {
  return /^[A-Za-z0-9_.-]{3,32}$/.test(username);
}

export function validatePassword(password) {
  return typeof password === "string" && password.length >= 10 && password.length <= 256;
}

async function passwordMatches(password, salt, expectedHash) {
  if (!validatePassword(password)) return false;
  const candidate = await derivePassword(password, salt);
  if (candidate.length !== expectedHash.length) return false;
  let diff = 0;
  for (let i = 0; i < candidate.length; i += 1) diff |= candidate.charCodeAt(i) ^ expectedHash.charCodeAt(i);
  return diff === 0;
}

export async function register(env, username, password) {
  username = String(username || "").trim();
  if (!validateUsername(username)) throw new Error("Username must be 3-32 characters using letters, numbers, ., _, or -");
  if (!validatePassword(password)) throw new Error("Password must be 10-256 characters");
  if (password !== password.trim()) throw new Error("Password cannot begin or end with spaces");
  if (!(await registrationOpen(env))) throw new Error("Registration is closed");

  const salt = crypto.getRandomValues(new Uint8Array(16));
  const passwordHash = await derivePassword(password, salt);
  const now = Date.now();
  try {
    const result = await env.DB.prepare(
      "INSERT INTO auth_users (username, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
    ).bind(username, base64url(salt), passwordHash, now).run();
    return { id: Number(result.meta.last_row_id), username };
  } catch (error) {
    if (String(error?.message || error).toLowerCase().includes("unique")) throw new Error("Registration is closed");
    throw error;
  }
}

export async function authenticate(env, username, password) {
  username = String(username || "").trim();
  const row = await env.DB.prepare(
    "SELECT id, username, password_salt, password_hash FROM auth_users WHERE username = ? COLLATE NOCASE LIMIT 1",
  ).bind(username).first();
  if (!row || typeof password !== "string") return null;
  const salt = decodeBase64url(row.password_salt);
  if (await passwordMatches(password, salt, row.password_hash)) {
    return { id: Number(row.id), username: row.username };
  }
  const trimmed = password.trim();
  if (trimmed !== password && await passwordMatches(trimmed, salt, row.password_hash)) {
    return { id: Number(row.id), username: row.username };
  }
  return null;
}

export async function createSession(env, userId) {
  const token = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const tokenHash = await sha256(token);
  const now = Date.now();
  const expiresAt = now + SESSION_TTL_SECONDS * 1000;
  await env.DB.prepare(
    "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
  ).bind(tokenHash, userId, now, expiresAt).run();
  return { token, cookie: cookieHeader(token), expiresAt };
}

export async function currentUser(request, env) {
  const token = requestToken(request);
  if (!token) return null;
  const tokenHash = await sha256(token);
  const now = Date.now();
  const row = await env.DB.prepare(
    "SELECT u.id, u.username, s.expires_at FROM auth_sessions s JOIN auth_users u ON u.id = s.user_id WHERE s.token_hash = ? LIMIT 1",
  ).bind(tokenHash).first();
  if (!row) return null;
  if (Number(row.expires_at) <= now) {
    await env.DB.prepare("DELETE FROM auth_sessions WHERE token_hash = ?").bind(tokenHash).run();
    return null;
  }
  return { id: Number(row.id), username: row.username };
}

export async function destroySession(request, env) {
  const token = requestToken(request);
  if (token) {
    const tokenHash = await sha256(token);
    await env.DB.prepare("DELETE FROM auth_sessions WHERE token_hash = ?").bind(tokenHash).run();
  }
  return clearCookieHeader();
}

export async function purgeExpiredSessions(env) {
  await env.DB.prepare("DELETE FROM auth_sessions WHERE expires_at <= ?").bind(Date.now()).run();
}
