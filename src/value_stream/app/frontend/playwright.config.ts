import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../../..", import.meta.url));
export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:18081",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${process.env.VALUE_STREAM_TEST_PYTHON || ".venv/bin/python"} -m value_stream.app --port 18081`,
    cwd: root,
    url: "http://127.0.0.1:18081/ready",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
