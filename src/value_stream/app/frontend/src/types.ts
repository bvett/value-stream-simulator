import type { components } from "./api.generated";
export type Workspace = components["schemas"]["Workspace"];
export type Definition = components["schemas"]["ScenarioDefinition-Output"];
export type Settings = components["schemas"]["ModelSettings-Output"];
export type TaskSpec = components["schemas"]["TaskSetSpec-Output"];
export type Preview = components["schemas"]["Preview"];
export type Run = components["schemas"]["RunStatus"];
export type Outcome = components["schemas"]["OutcomeSummary"];
export type ResultView = components["schemas"]["ResultView"];
export type RunRequest = components["schemas"]["RunRequest"];
export type Config = components["schemas"]["AppConfig"];
export type Observation = components["schemas"]["Observation"];
export const terminal = (run: Run) =>
  ["completed", "completed_with_errors", "cancelled", "failed"].includes(
    run.state,
  );
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method,
    signal,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const value = await response.json();
  if (!response.ok)
    throw new ApiError(
      value.code || "REQUEST_FAILED",
      value.message || "Request failed",
      value.details,
    );
  return value as T;
}
