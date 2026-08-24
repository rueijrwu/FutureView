import { existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const ROOT = ".local-data/objects";

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function rel(file) {
  return path.relative(ROOT, file).split(path.sep).join("/");
}

function extractDate(key) {
  const match = key.match(/(?:^|\/)date=(\d{4}-\d{2}-\d{2})(?:\/|$)/);
  return match?.[1] ?? null;
}

function summarizePrefix(files, prefix) {
  const rows = files.filter((file) => rel(file).startsWith(prefix));
  const dates = [...new Set(rows.map((file) => extractDate(rel(file))).filter(Boolean))].sort();
  const bytes = rows.reduce((sum, file) => sum + statSync(file).size, 0);
  return {
    prefix,
    objects: rows.length,
    sessions: dates.length,
    start: dates[0] ?? null,
    end: dates.at(-1) ?? null,
    bytes,
  };
}

function fmtMiB(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

if (!existsSync(ROOT)) {
  console.error("[local:data-report] .local-data/objects is missing; run npm run local:sync first");
  process.exit(1);
}

const files = walk(ROOT);
const summaries = [
  summarizePrefix(files, "prices/daily/"),
  summarizePrefix(files, "prices/daily-json/"),
  summarizePrefix(files, "features/"),
  summarizePrefix(files, "rankings/"),
  summarizePrefix(files, "top50/"),
  summarizePrefix(files, "work/feature-bootstrap/"),
];

console.log("FutureView local data inventory\n");
console.log(`[local:data-report] total R2 objects mirrored: ${files.length}`);
for (const row of summaries) {
  console.log(
    `[local:data-report] ${row.prefix} objects=${row.objects} sessions=${row.sessions}`
    + ` range=${row.start ?? "n/a"} -> ${row.end ?? "n/a"} size=${fmtMiB(row.bytes)}`,
  );
}

const priceCandidates = summaries.filter((row) => row.prefix.startsWith("prices/") && row.sessions > 0);
const best = priceCandidates.sort((a, b) => b.sessions - a.sessions)[0] ?? null;
if (best) {
  console.log(`\n[local:data-report] best historical price source: ${best.prefix}`);
  console.log(`[local:data-report] ${best.sessions} sessions (${best.start} -> ${best.end})`);
} else {
  console.log("\n[local:data-report] no historical price sessions found in mirrored R2 objects");
}
