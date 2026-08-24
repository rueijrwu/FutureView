function fail(message) {
  console.error(`\n[cloudflare:smoke] ERROR: ${message}`);
  process.exit(1);
}

function baseUrl() {
  const arg = process.argv.slice(2).find((value) => value.startsWith("--base-url="));
  const raw = arg?.slice("--base-url=".length) || process.env.FUTUREVIEW_API_BASE_URL || "";
  if (!raw) fail("set FUTUREVIEW_API_BASE_URL or pass --base-url=https://...");
  return raw.replace(/\/$/, "");
}

async function getJson(base, path) {
  const response = await fetch(`${base}${path}`, {
    headers: { Accept: "application/json", "User-Agent": "FutureView-Cloudflare-Smoke/1.0" },
  });
  const text = await response.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { /* keep raw detail below */ }
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}: ${text.slice(0, 300)}`);
  }
  return payload;
}

const base = baseUrl();
console.log(`[cloudflare:smoke] target ${base}`);

const health = await getJson(base, "/api/health");
if (health?.runtime !== "cloudflare-js") fail(`/api/health runtime=${health?.runtime ?? "missing"}; expected cloudflare-js`);
if (health?.storage !== "r2") fail(`/api/health storage=${health?.storage ?? "missing"}; expected r2`);
if (health?.database !== "d1-bound") fail(`/api/health database=${health?.database ?? "missing"}; expected d1-bound`);
console.log("[cloudflare:smoke] health: Worker + R2 + D1 bindings OK");

const universe = await getJson(base, "/api/universe/status");
if (!universe || typeof universe !== "object") fail("R2 universe status returned no JSON object");
console.log(`[cloudflare:smoke] R2 read: universe ${universe.as_of ?? "date unknown"}`);

const history = await getJson(base, "/api/rankings/history?limit=1");
if (history?.source !== "d1" || !Array.isArray(history?.dates)) {
  fail("D1 ranking history contract failed");
}
console.log(`[cloudflare:smoke] D1 read: ranking history rows=${history.dates.length}`);

console.log("\n[cloudflare:smoke] READY");
console.log("[cloudflare:smoke] deployed API contracts for Worker/R2/D1 are readable");
console.log("[cloudflare:smoke] this smoke test performs no production writes or workflows");
