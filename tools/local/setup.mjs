import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import process from "node:process";

const WRANGLER_VERSION = "4.125.0";
const LOCAL_CONFIG = ".wrangler.local.json";
const DEV_VARS = ".dev.vars";
const DEV_VARS_EXAMPLE = ".dev.vars.example";
const LOCAL_D1_ID = "00000000-0000-0000-0000-000000000000";

function fail(message) {
  console.error(`\n[local:setup] ERROR: ${message}`);
  process.exit(1);
}

function run(command, args) {
  console.log(`\n> ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error) fail(result.error.message);
  if (result.status !== 0) fail(`${command} exited with code ${result.status}`);
}

function nodeMajor() {
  return Number(process.versions.node.split(".")[0]);
}

function generateLocalWranglerConfig() {
  const source = JSON.parse(readFileSync("wrangler.jsonc", "utf8"));
  source.d1_databases = [{
    binding: "DB",
    database_name: "futureview",
    database_id: LOCAL_D1_ID,
    migrations_dir: "migrations",
  }];
  writeFileSync(LOCAL_CONFIG, `${JSON.stringify(source, null, 2)}\n`);
  console.log(`[local:setup] Generated ${LOCAL_CONFIG}`);
}

function ensureDevVars() {
  if (existsSync(DEV_VARS)) {
    console.log(`[local:setup] Keeping existing ${DEV_VARS}`);
    return;
  }
  if (!existsSync(DEV_VARS_EXAMPLE)) fail(`${DEV_VARS_EXAMPLE} is missing`);
  writeFileSync(DEV_VARS, readFileSync(DEV_VARS_EXAMPLE, "utf8"));
  console.log(`[local:setup] Created ${DEV_VARS} from ${DEV_VARS_EXAMPLE}`);
}

console.log("FutureView local environment setup");
console.log(`Node ${process.versions.node} on ${process.platform}`);

if (nodeMajor() < 22) fail("Node.js 22+ is required; Node.js 24 is recommended to match CI.");

run("npm", ["--version"]);
ensureDevVars();
generateLocalWranglerConfig();

if (existsSync("view/package-lock.json")) run("npm", ["ci", "--prefix", "view"]);
else run("npm", ["install", "--prefix", "view"]);

run("npx", ["--yes", `wrangler@${WRANGLER_VERSION}`, "d1", "migrations", "apply", "futureview", "--local", "--config", LOCAL_CONFIG]);
run("npm", ["run", "local:check"]);

console.log("\n[local:setup] READY");
console.log("Start development with: npm run local:dev");
console.log("Recommended environment: Ubuntu WSL / Linux");
