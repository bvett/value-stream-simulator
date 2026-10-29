import { test, expect, type Page, type Browser } from "@playwright/test";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
const root = fileURLToPath(new URL("../../../../..", import.meta.url));
const manifest = JSON.parse(
  readFileSync(
    join(root, "src/value_stream/service/persistence/samples/manifest.json"),
    "utf8",
  ),
) as {
  examples: {
    slug: string;
    url: string;
    run_ids: string[];
    scenario_id: string | null;
    workspace_id: string;
  }[];
};
const tabs = [
  "team-size",
  "deployment-interval",
  "stage-loss",
  "resource-utilization",
  "resource-backlog",
];
async function verify(page: Page, url: string) {
  const submissions: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/runs"))
      submissions.push(request.url());
  });
  await page.goto(url);
  const query = new URL(url, "http://fixture").searchParams;
  await expect(
    page.getByRole("tab").nth(tabs.indexOf(query.get("tab")!)),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".js-plotly-plot").first()).toBeVisible({
    timeout: 30000,
  });
  await expect
    .poll(() => page.locator(".js-plotly-plot .trace").count(), {
      timeout: 30000,
    })
    .toBeGreaterThan(0);
  if (query.has("scenario"))
    await expect(
      page.getByRole("combobox", { name: "Detail selection" }),
    ).toHaveValue(query.get("scenario")!);
  expect(new URL(page.url()).searchParams.getAll("run")).toEqual(
    query.getAll("run"),
  );
  await expect(page.locator("#export-run")).toHaveValue(query.getAll("run")[0]);
  const csv = await page.request.get(
    new URL(page.url()).origin +
      `/api/v1/workspaces/${query.get("workspace")}/runs/${query.getAll("run")[0]}/exports/summary`,
  );
  expect(csv.ok()).toBeTruthy();
  expect((await csv.text()).split("\n").length).toBeGreaterThan(2);
  await page.reload();
  await expect(page.locator(".js-plotly-plot").first()).toBeVisible();
  await expect
    .poll(() => page.locator(".js-plotly-plot .trace").count(), {
      timeout: 30000,
    })
    .toBeGreaterThan(0);
  if (query.has("scenario"))
    await expect(
      page.getByRole("combobox", { name: "Detail selection" }),
    ).toHaveValue(query.get("scenario")!);
  await expect(
    page.getByRole("link", { name: "Open README example", exact: true }),
  ).toBeVisible();
  expect(submissions).toEqual([]);
}
for (const example of manifest.examples)
  test(`fresh README link: ${example.slug}`, async ({ page }) => {
    await verify(page, example.url);
    if (example.slug === "efficiency-11" || example.slug === "small-team")
      await page.screenshot({
        path: join(
          root,
          `.agent/artifacts/sqlite-persistence/${example.slug}.png`,
        ),
        fullPage: true,
      });
    if (example.slug === "efficiency-11") {
      const reversed = new URL(page.url());
      reversed.searchParams.delete("run");
      [...example.run_ids]
        .reverse()
        .forEach((id) => reversed.searchParams.append("run", id));
      await verify(page, reversed.toString());
      await expect(page.locator(".legendtext").first()).toContainText(
        "README efficiency 11",
      );
    }
    if (example.slug === "small-team") {
      const selected = new URL(page.url()).searchParams.get("scenario");
      await page
        .getByRole("checkbox", { name: /README efficiency 11/ })
        .check();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("scenario"))
        .toBe(selected);
      await page.getByRole("checkbox", { name: /README baseline/ }).uncheck();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("scenario"))
        .toBeNull();
    }
  });
const restartPort = process.env.VALUE_STREAM_RESTART_TEST_PORT || "18082";
const base = `http://127.0.0.1:${restartPort}`;
async function start(directory: string): Promise<ChildProcess> {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    VALUE_STREAM_DATA_DIR: directory,
    VALUE_STREAM_SERVICE_URL: "http://127.0.0.1:1",
  };
  delete env.VALUE_STREAM_APP_DATABASE;
  delete env.VALUE_STREAM_SERVICE_DATABASE;
  const python =
    process.env.VALUE_STREAM_TEST_PYTHON ||
    join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
  const child = spawn(
    python,
    ["-m", "value_stream.app", "--port", restartPort, "--data-dir", directory],
    { cwd: root, env, stdio: "pipe" },
  );
  let log = "";
  child.stderr?.on("data", (data) => {
    log += String(data);
  });
  child.stdout?.on("data", () => {});
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(log);
    try {
      if ((await fetch(base + "/health")).ok) return child;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  child.kill("SIGINT");
  throw new Error("Restart server did not become ready: " + log);
}
async function stop(child: ChildProcess) {
  if (child.exitCode !== null) return;
  const exited = new Promise<void>((resolve) =>
    child.once("exit", () => resolve()),
  );
  child.kill("SIGINT");
  await exited;
}
async function fresh(browser: Browser, url: string) {
  const context = await browser.newContext();
  try {
    await verify(await context.newPage(), url);
  } finally {
    await context.close();
  }
}
test("exact links survive a real restart, historical context, and deletion", async ({
  browser,
  request,
}) => {
  test.setTimeout(240000);
  const directory = mkdtempSync(join(tmpdir(), "value-stream-restart-"));
  let server: ChildProcess | undefined;
  try {
    server = await start(directory);
    for (const example of manifest.examples)
      await fresh(browser, base + example.url);
    await stop(server);
    server = await start(directory);
    for (const example of manifest.examples)
      await fresh(browser, base + example.url);
    const first = manifest.examples[0],
      path = base + `/api/v1/workspaces/${first.workspace_id}`;
    const workspace = await (await request.get(path)).json();
    await request.put(path + "/editor", {
      data: {
        expected_revision: workspace.revision,
        task_spec: { ...workspace.task_spec, count: 3 },
        definitions: workspace.definitions,
      },
    });
    const editorBefore = await (await request.get(path)).json();
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await verify(page, base + first.url);
      await expect(
        page.getByText(/Viewing a historical task set/),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Preview sweep", exact: true }),
      ).toBeDisabled();
      const editorAfter = await (await request.get(path)).json();
      expect(editorAfter.current_task_set).toBe(editorBefore.current_task_set);
      expect(editorAfter.revision).toBe(editorBefore.revision);
      expect(editorAfter.task_spec.count).toBe(3);
      await page.goto(
        base +
          first.url.replace(
            first.run_ids[0],
            "00000000-0000-4000-8000-000000000099",
          ),
      );
      await expect(page.getByText(/saved view is unavailable/)).toBeVisible();
      await request.delete(path);
      await page.goto(base + first.url);
      await expect(page.locator(".startup")).toContainText(
        /not found|unavailable/i,
      );
      const examples = await (
        await request.get(base + "/api/v1/examples")
      ).json();
      expect(examples.examples).toEqual([]);
    } finally {
      await context.close();
    }
  } finally {
    if (server) await stop(server);
    rmSync(directory, { recursive: true, force: true });
  }
});
