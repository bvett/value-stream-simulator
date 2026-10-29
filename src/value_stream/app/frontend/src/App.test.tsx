import { cleanup, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import type { Workspace, Run } from "./types";
const w = "00000000-0000-4000-8000-000000000001",
  a = "00000000-0000-4000-8000-000000000002",
  b = "00000000-0000-4000-8000-000000000003",
  t = "00000000-0000-4000-8000-000000000004";
const spec: Workspace["task_spec"] = {
  name: "Work",
  count: 2,
  seed: 42,
  depreciation_rate: 0.02,
  story_points: { kind: "constant", value: 1 },
  initial_value: { kind: "constant", value: 1 },
};
const run = (id: string, name: string): Run => ({
  id,
  name,
  task_set_id: t,
  state: "completed",
  intent: "manual",
  job_id: null,
  last_cursor: 0,
  error: null,
  pinned: false,
  superseded: false,
  cancel_requested: false,
  retry_paused: false,
  outcomes: [],
});
const workspace: Workspace = {
  id: w,
  revision: 1,
  task_spec: spec,
  definitions: [],
  task_sets: [
    {
      id: t,
      revision: 1,
      spec,
      content_hash: "hash",
      tasks: [],
      generator_version: "1",
    },
  ],
  current_task_set: t,
  baseline_id: a,
  latest_id: b,
  runs: [run(a, "A"), run(b, "B")],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});
it("preserves URL order and tab across polling and back navigation", async () => {
  history.replaceState(
    null,
    "",
    `/?workspace=${w}&run=${b}&run=${a}&tab=resource-backlog&tracking=yes`,
  );
  sessionStorage.setItem("value-stream-tab", "1");
  let reads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      let value: unknown;
      if (path.includes("/workspaces/")) {
        reads++;
        value = {
          ...workspace,
          runs: reads > 1 ? [...workspace.runs].reverse() : workspace.runs,
        };
      } else if (path.includes("/examples"))
        value = { release: "test", examples: [] };
      else
        value = { limits: { max_models: 500, max_tasks: 1000 }, ready: true };
      return new Response(JSON.stringify(value), { status: 200 });
    }),
  );
  render(<App />);
  await waitFor(() =>
    expect(
      screen
        .getByRole("tab", { name: "Resource backlog" })
        .getAttribute("aria-selected"),
    ).toBe("true"),
  );
  await new Promise((r) => setTimeout(r, 1100));
  expect(reads).toBeGreaterThan(1);
  expect(new URLSearchParams(location.search).getAll("run")).toEqual([b, a]);
  expect(new URLSearchParams(location.search).get("tracking")).toBe("yes");
  act(() => {
    history.replaceState(null, "", `/?workspace=${w}&run=${a}&tab=team-size`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("tab", { name: "Value lost / team size" })
        .getAttribute("aria-selected"),
    ).toBe("true"),
  );
  expect(new URLSearchParams(location.search).getAll("run")).toEqual([a]);
});
it("shows unavailable selections without creating another workspace", async () => {
  history.replaceState(null, "", `/?workspace=${w}&run=${t}`);
  const fetch = vi.fn(
    async () => new Response(JSON.stringify(workspace), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetch);
  render(<App />);
  await screen.findByText(/saved view is unavailable/);
  expect(fetch).toHaveBeenCalledTimes(1);
});
