import type { Workspace } from "./types";

export const tabSlugs = [
  "team-size",
  "deployment-interval",
  "stage-loss",
  "resource-utilization",
  "resource-backlog",
] as const;
export type TabSlug = (typeof tabSlugs)[number];
export type ViewLocation = {
  workspace?: string;
  runs?: string[];
  scenario?: { run: string; id: string };
  tab?: TabSlug;
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const unavailable = () =>
  new Error(
    "This saved view is unavailable. Check its workspace, comparisons, scenario, and chart tab.",
  );
export function parseLocation(search: string): ViewLocation {
  const params = new URLSearchParams(search);
  for (const key of ["workspace", "scenario", "tab"])
    if (params.getAll(key).length > 1) throw unavailable();
  const workspace = params.get("workspace") ?? undefined;
  const runs = params.has("run") ? params.getAll("run") : undefined;
  const detail = params.get("scenario")?.split("/");
  const tab = params.get("tab") ?? undefined;
  if (
    (workspace !== undefined && !uuid.test(workspace)) ||
    runs?.some((r) => !uuid.test(r)) ||
    (runs && new Set(runs).size !== runs.length) ||
    (detail && (detail.length !== 2 || detail.some((v) => !uuid.test(v)))) ||
    (tab !== undefined && !tabSlugs.some((t) => t === tab)) ||
    ((runs || detail || tab) && !workspace) ||
    (detail && !runs?.includes(detail[0]))
  )
    throw unavailable();
  return {
    workspace,
    runs,
    scenario: detail ? { run: detail[0], id: detail[1] } : undefined,
    tab: tabSlugs.find((t) => t === tab),
  };
}
export function serializeLocation(view: ViewLocation, search = ""): string {
  const params = new URLSearchParams(search);
  for (const key of ["workspace", "run", "scenario", "tab"]) params.delete(key);
  if (view.workspace) params.set("workspace", view.workspace);
  view.runs?.forEach((r) => params.append("run", r));
  if (view.scenario)
    params.set("scenario", `${view.scenario.run}/${view.scenario.id}`);
  if (view.tab) params.set("tab", view.tab);
  const result = `?${params.toString()}`;
  parseLocation(result);
  return result;
}
export function validateLocation(
  view: ViewLocation,
  workspace: Workspace,
): string | null {
  if (view.workspace !== workspace.id) throw unavailable();
  const runs = view.runs?.map((id) => workspace.runs.find((r) => r.id === id));
  if (
    runs?.some((r) => !r) ||
    new Set(runs?.map((r) => r?.task_set_id)).size > 1
  )
    throw unavailable();
  const context = runs?.[0]?.task_set_id ?? workspace.current_task_set;
  if (context && !workspace.task_sets.some((t) => t.id === context))
    throw unavailable();
  if (
    view.scenario &&
    !runs
      ?.find((r) => r?.id === view.scenario?.run)
      ?.outcomes.some(
        (o) => o.scenario.id === view.scenario?.id && o.status === "succeeded",
      )
  )
    throw unavailable();
  return context ?? null;
}
