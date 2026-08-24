import { spawn } from "node:child_process";
import process from "node:process";

const children = [];
let shuttingDown = false;

function start(label, command, args) {
  const child = spawn(command, args, {
    stdio: "inherit",
    env: process.env,
  });
  children.push(child);

  child.on("error", (error) => {
    console.error(`[local:dev] ${label} failed to start: ${error.message}`);
    shutdown(1);
  });

  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    const detail = signal ? `signal ${signal}` : `code ${code ?? 0}`;
    console.error(`[local:dev] ${label} exited (${detail}); stopping local dev stack`);
    shutdown(code === 0 ? 0 : 1);
  });

  return child;
}

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(exitCode), 250).unref();
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log("FutureView local development stack");
console.log("[local:dev] API:      http://localhost:8787");
console.log("[local:dev] Frontend: http://localhost:5173");
console.log("[local:dev] Backtest: http://localhost:5173/backtest");

start("api", process.execPath, ["tools/local/api.mjs"]);
start("frontend", "npm", ["run", "dev", "--prefix", "view", "--", "--host", "0.0.0.0"]);
