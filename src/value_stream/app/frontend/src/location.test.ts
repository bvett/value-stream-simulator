import { describe, expect, it } from "vitest";
import {
  parseLocation,
  serializeLocation,
  validateLocation,
  tabSlugs,
} from "./location";
import type { Workspace } from "./types";
const w = "00000000-0000-4000-8000-000000000001",
  a = "00000000-0000-4000-8000-000000000002",
  b = "00000000-0000-4000-8000-000000000003",
  s = "00000000-0000-4000-8000-000000000004";
describe("view URLs", () => {
  it("round trips ordered comparisons and scoped detail, preserving other parameters", () => {
    for (const tab of tabSlugs) {
      const value = {
        workspace: w,
        runs: [b, a],
        scenario: { run: b, id: s },
        tab,
      };
      const search = serializeLocation(
        value,
        "?tracking=yes&workspace=old&run=old",
      );
      expect(search).toContain("%2F");
      expect(search).toContain("tracking=yes");
      expect(parseLocation(search)).toEqual(value);
    }
  });
  it("accepts workspace-only legacy links", () =>
    expect(parseLocation(`?workspace=${w}`).runs).toBeUndefined());
  it.each([
    "?workspace=bad",
    `?workspace=${w}&tab=unknown`,
    `?workspace=${w}&run=${a}&run=${a}`,
    `?workspace=${w}&scenario=${a}/${s}`,
    `?workspace=${w}&run=${a}&scenario=${b}/${s}`,
    `?workspace=${w}&workspace=${w}`,
    `?run=${a}`,
  ])("rejects unavailable explicit values %s", (search) =>
    expect(() => parseLocation(search)).toThrow(/unavailable/),
  );
  it("validates ownership, task context, and exact scenario membership", () => {
    const workspace = {
      id: w,
      current_task_set: "current",
      task_sets: [{ id: "historical" }],
      runs: [
        {
          id: a,
          task_set_id: "historical",
          outcomes: [{ scenario: { id: s }, status: "succeeded" }],
        },
        { id: b, task_set_id: "other", outcomes: [] },
      ],
    } as unknown as Workspace;
    expect(
      validateLocation(
        { workspace: w, runs: [a], scenario: { run: a, id: s } },
        workspace,
      ),
    ).toBe("historical");
    expect(() =>
      validateLocation({ workspace: w, runs: [a, b] }, workspace),
    ).toThrow();
    expect(() =>
      validateLocation({ workspace: w, runs: [s] }, workspace),
    ).toThrow();
    expect(() =>
      validateLocation({ workspace: a, runs: [a] }, workspace),
    ).toThrow();
  });
});
