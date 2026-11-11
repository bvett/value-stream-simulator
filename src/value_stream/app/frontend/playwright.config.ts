import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import * as path from "path";
const root = fileURLToPath(new URL("../../../..", import.meta.url));
let pyexe = path.join(root, ".venv", "bin", "python");
if (process.platform == "win32") {
  pyexe = path.join(root, ".venv", "Scripts", "python.exe");
}

const port = Number(process.env.VALUE_STREAM_TEST_PORT || 18081);

export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${process.env.VALUE_STREAM_TEST_PYTHON || pyexe} ${path.join(root, "tests", "browser_server.py")} --port ${port}`,
    cwd: root,
    url: `http://127.0.0.1:${port}/ready`,
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10000 },
    timeout: 30000,
  },
});
