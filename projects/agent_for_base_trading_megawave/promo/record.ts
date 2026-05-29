import { spawnSync } from "node:child_process";

// TypeScript bridge kept for the production plan contract.
// The local workspace currently has Python Playwright installed, while the Node
// playwright package is not present. This bridge delegates to the runnable
// Python recorder used by `python3 promo/build.py`.
const result = spawnSync("python", ["-m", "promo.record", ...process.argv.slice(2)], {
  cwd: new URL("..", import.meta.url).pathname,
  stdio: "inherit",
});

process.exit(result.status ?? 1);
