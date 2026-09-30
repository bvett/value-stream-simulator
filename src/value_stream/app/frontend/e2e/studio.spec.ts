import { expect, test } from "@playwright/test";

test("real simulations, baseline, interactive cache, exports, refresh, plots and accessibility", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find where value slips away." }),
  ).toBeVisible();
  await page.getByLabel("Task count", { exact: true }).fill("12");
  await page
    .getByRole("button", { name: "Preview sweep", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Run 9 scenarios/ }),
  ).toBeEnabled();
  await page.getByRole("button", { name: /Run 9 scenarios/ }).click();
  await expect(page.locator(".status-succeeded")).toHaveCount(9, {
    timeout: 30000,
  });
  await expect(page.locator(".js-plotly-plot")).toBeVisible();
  await expect(page.locator(".chart")).toHaveAttribute(
    "data-rendered-tab",
    "0",
  );
  const xRange = () =>
    page
      .locator(".js-plotly-plot")
      .evaluate((el) => [...(el as any)._fullLayout.xaxis.range]);
  const originalRange = await xRange();
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(xRange).not.toEqual(originalRange);
  const zoomedRange = await xRange();
  await page.getByLabel("Interactive mode", { exact: true }).check();
  await page.getByLabel("Interactive value", { exact: true }).fill("1");
  await page.getByLabel("Interactive value", { exact: true }).press("Enter");
  await expect(page.locator(".status-succeeded")).toHaveCount(12, {
    timeout: 30000,
  });
  await expect.poll(xRange).toEqual(zoomedRange);
  await page.getByText("Baseline comparison", { exact: true }).first().click();
  await expect(
    page.getByText(/percentage points.*Observed difference/).first(),
  ).toBeVisible();
  await page.getByText("Baseline comparison", { exact: true }).first().click();
  await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
  await expect.poll(xRange).toEqual(originalRange);
  await page
    .getByRole("button", { name: "Pin Deployment interval: 1", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Unpin Deployment interval: 1",
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator(".status-succeeded")).toHaveCount(12);
  await expect(
    page.getByRole("button", {
      name: "Unpin Deployment interval: 1",
      exact: true,
    }),
  ).toBeVisible();
  for (const name of [
    "Mean stage loss",
    "Resource utilization",
    "Resource backlog",
  ]) {
    await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.locator(".chart")).toHaveAttribute(
      "data-rendered-tab",
      String(
        ["Mean stage loss", "Resource utilization", "Resource backlog"].indexOf(
          name,
        ) + 2,
      ),
    );
  }
  await expect(
    page.getByText("Requests may contain batches", { exact: false }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "summary CSV ↓" }).click();
  expect((await download).suggestedFilename()).toMatch(/^summary-/);
  await page
    .getByRole("tab", { name: "Value lost / team size", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Value lost / team size", exact: true })
    .press("ArrowRight");
  await expect(
    page.getByRole("tab", {
      name: "Value lost / deployment interval",
      exact: true,
    }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
  await expect(page.locator(".chart")).toHaveAttribute(
    "data-rendered-tab",
    "1",
  );
  await page.locator(".plot-card").screenshot({
    path: testInfo.outputPath("chart.png"),
  });
  await page.screenshot({
    path: testInfo.outputPath("desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Results & comparisons" }),
  ).toBeVisible();
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(noOverflow).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("mobile.png"),
    fullPage: true,
  });
  await expect(page.getByRole("alert")).toHaveCount(0);
  // A 720-CSS-pixel viewport is the reflow available at 200% browser zoom on a 1440px display.
  await page.setViewportSize({ width: 720, height: 500 });
  await expect(
    page.getByRole("button", { name: "Reset zoom", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("zoom-200.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("invalid ranges, body limits and stale previews return documented errors", async ({
  request,
}) => {
  const w = await (await request.post("/api/v1/workspaces")).json();
  const path = `/api/v1/workspaces/${w.id}`;
  const invalid = await request.put(`${path}/editor`, {
    data: {
      expected_revision: 0,
      task_spec: { ...w.task_spec, count: 1001 },
      definitions: w.definitions,
    },
  });
  expect(invalid.status()).toBe(422);
  expect((await invalid.json()).code).toBe("LIMIT_EXCEEDED");
  const preview = await (
    await request.put(`${path}/editor`, {
      data: {
        expected_revision: 0,
        task_spec: w.task_spec,
        definitions: w.definitions,
      },
    })
  ).json();
  expect(preview.count).toBe(9);
  const stale = await request.post(`${path}/runs`, {
    data: {
      request_id: "abca3594-7b58-4c43-bfb8-8831103a7856",
      preview_digest: "wrong",
    },
  });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).code).toBe("REVISION_CONFLICT");
  await request.delete(path);
});

test("incremental results stay visible when cancelling a whole job", async ({
  page,
  request,
}) => {
  const w = await (await request.post("/api/v1/workspaces")).json();
  const path = `/api/v1/workspaces/${w.id}`;
  w.task_spec.count = 1000;
  w.definitions[0].sweeps = {
    team_size: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    deployment_cadence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  };
  await request.put(`${path}/editor`, {
    data: {
      expected_revision: 0,
      task_spec: w.task_spec,
      definitions: w.definitions,
    },
  });
  await page.goto(`/?workspace=${w.id}`);
  await page
    .getByRole("button", { name: "Preview sweep", exact: true })
    .click();
  await page.getByRole("button", { name: /Run 100 scenarios/ }).click();
  await expect
    .poll(() => page.locator(".status-succeeded").count(), { timeout: 30000 })
    .toBeGreaterThan(0);
  const completed = await page.locator(".status-succeeded").count();
  expect(completed).toBeLessThan(100);
  await page.getByRole("button", { name: "Cancel job", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Cancel job", exact: true }),
  ).toHaveCount(0, { timeout: 30000 });
  await expect
    .poll(() => page.locator(".status-cancelled").count())
    .toBeGreaterThan(0);
  expect(
    await page.locator(".status-succeeded").count(),
  ).toBeGreaterThanOrEqual(completed);
  await page.reload();
  await expect
    .poll(() => page.locator(".status-cancelled").count())
    .toBeGreaterThan(0);
});
