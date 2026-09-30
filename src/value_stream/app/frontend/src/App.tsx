import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, ApiError, terminal } from "./types";
import type {
  Workspace,
  TaskSpec,
  Definition,
  Preview,
  Run,
  Outcome,
  ResultView,
  RunRequest,
  Config,
  Settings,
} from "./types";
import {
  TaskEditor,
  ModelEditor,
  fields,
  fieldScale,
  displayValue,
} from "./editors";
const Charts = lazy(() =>
  import("./charts").then((module) => ({ default: module.Charts })),
);
const tabs = [
  "Value lost / team size",
  "Value lost / deployment interval",
  "Mean stage loss",
  "Resource utilization",
  "Resource backlog",
];
const percent = (v: number | null | undefined) =>
  v == null ? "N/A" : `${v.toFixed(2)}%`;

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace>();
  const [taskSpec, setTaskSpec] = useState<TaskSpec>();
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [dirty, setDirty] = useState(true);
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<Config>();
  const [tab, setTab] = useState(
    Number(sessionStorage.getItem("value-stream-tab") || 0),
  );
  const [zoomRevision, setZoomRevision] = useState(0);
  const [seriesLimit, setSeriesLimit] = useState(12);
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [detailViews, setDetailViews] = useState<
    { run: Run; outcome: Outcome; view: ResultView }[]
  >([]);
  const [detailSelection, setDetailSelection] = useState("");
  const [interactive, setInteractive] = useState(false);
  const [property, setProperty] =
    useState<keyof Settings>("deployment_cadence");
  const [familyValue, setFamilyValue] = useState<string>("");
  const [interactiveValue, setInteractiveValue] = useState<
    number | string | null
  >(1);
  const [exportRun, setExportRun] = useState("");
  const [comparisonName, setComparisonName] = useState("Baseline");
  const workspaceRef = useRef<Workspace | undefined>(undefined);
  const pending = useRef<RunRequest | null>(null);
  const sending = useRef(false);
  const sliderTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const lastSent = useRef(0);
  const lastInteractive = useRef("");
  const detailCache = useRef(new Map<string, ResultView>());

  const load = useCallback(async (id: string, restoreEditor = false) => {
    const w = await api<Workspace>(`/api/v1/workspaces/${id}`);
    workspaceRef.current = w;
    setWorkspace(w);
    if (restoreEditor) {
      setTaskSpec(w.task_spec);
      setDefinitions(w.definitions);
      setDirty(true);
      setPreview(undefined);
    }
    return w;
  }, []);

  useEffect(() => {
    let disposed = false;
    async function init() {
      try {
        const id =
          new URLSearchParams(location.search).get("workspace") ||
          localStorage.getItem("value-stream-workspace");
        let w: Workspace;
        if (id) w = await api<Workspace>(`/api/v1/workspaces/${id}`);
        else w = await api<Workspace>("/api/v1/workspaces", "POST");
        if (disposed) return;
        localStorage.setItem("value-stream-workspace", w.id);
        history.replaceState(null, "", `?workspace=${w.id}`);
        workspaceRef.current = w;
        setWorkspace(w);
        setTaskSpec(w.task_spec);
        setDefinitions(w.definitions);
        setConfig(await api<Config>("/api/v1/config"));
      } catch (e) {
        if (!disposed) setError(e as Error);
      }
    }
    void init();
    return () => {
      disposed = true;
    };
  }, []);

  const selectedContext = workspace?.current_task_set;
  useEffect(() => {
    if (!workspace) return;
    const visible = workspace.runs
      .filter(
        (r) =>
          r.task_set_id === selectedContext &&
          (r.pinned ||
            r.id === workspace.baseline_id ||
            r.id === workspace.latest_id ||
            !terminal(r)),
      )
      .map((r) => r.id);
    setSelectedRuns(visible);
    const available = [...workspace.runs]
      .reverse()
      .find((r) => terminal(r) && r.task_set_id === selectedContext);
    if (available)
      setExportRun((current) =>
        workspace.runs.some(
          (r) => r.id === current && r.task_set_id === selectedContext,
        )
          ? current
          : available.id,
      );
  }, [
    workspace?.baseline_id,
    workspace?.latest_id,
    selectedContext,
    workspace?.runs.length,
    workspace?.runs.map((r) => `${r.id}:${r.pinned}:${r.state}`).join("|"),
  ]);

  useEffect(() => {
    if (!workspace) return;
    const timer = setInterval(() => {
      void load(workspace.id).catch((e) => setError(e));
    }, 1000);
    return () => clearInterval(timer);
  }, [workspace?.id, load]);

  const runs = workspace?.runs.filter((r) => selectedRuns.includes(r.id)) || [];
  const outcomes = runs.flatMap((run) =>
    run.outcomes.map((outcome) => ({ run, outcome })),
  );
  const successful = outcomes.filter((o) => o.outcome.status === "succeeded");
  const successfulKey = successful
    .map((o) => `${o.run.id}/${o.outcome.scenario.id}`)
    .join("|");
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    async function fetchDetails() {
      const selection = detailSelection
        ? successful.filter(
            (o) => `${o.run.id}/${o.outcome.scenario.id}` === detailSelection,
          )
        : successful.slice(0, Math.min(seriesLimit, 12));
      const result = [];
      for (const item of selection) {
        const key = `${item.run.id}/${item.outcome.scenario.id}`;
        let view = detailCache.current.get(key);
        if (!view) {
          view = await api<ResultView>(
            `/api/v1/workspaces/${workspace!.id}/runs/${item.run.id}/results/${item.outcome.scenario.id}`,
          );
          detailCache.current.set(key, view);
        }
        result.push({ ...item, view });
      }
      if (!cancelled) setDetailViews(result);
    }
    void fetchDetails().catch((e) => {
      if (!cancelled) setError(e);
    });
    return () => {
      cancelled = true;
    };
  }, [workspace?.id, successfulKey, detailSelection, seriesLimit]);

  const basePath = workspace ? `/api/v1/workspaces/${workspace.id}` : "";
  const active = workspace?.runs.find((r) => !terminal(r));
  const baseline = workspace?.runs.find((r) => r.id === workspace.baseline_id);
  const propertyScale = fieldScale(property);
  const familyValues = baseline
    ? [
        ...new Set(
          baseline.outcomes.map((o) =>
            JSON.stringify(o.scenario.settings[property]),
          ),
        ),
      ]
    : [];
  const effectiveFamily = familyValues.includes(familyValue)
    ? familyValue
    : familyValues[0] || "null";

  useEffect(() => {
    if (
      (tab === 0 && property === "team_size") ||
      (tab === 1 && property === "deployment_cadence")
    ) {
      setProperty(tab === 0 ? "deployment_cadence" : "team_size");
      setFamilyValue("");
      setInteractiveValue(1);
    }
  }, [tab, property]);

  function baselineDifference(run: Run, outcome: Outcome) {
    if (
      !baseline ||
      run.id === baseline.id ||
      run.task_set_id !== baseline.task_set_id ||
      outcome.loss_percent == null
    )
      return null;
    const keys = Object.keys(fields) as (keyof Settings)[];
    const changed = (other: Outcome) =>
      keys.filter(
        (key) =>
          outcome.scenario.settings[key] !== other.scenario.settings[key],
      );
    const candidates = baseline.outcomes
      .filter((o) => o.loss_percent != null)
      .sort((a, b) => changed(a).length - changed(b).length);
    const original =
      candidates.find((o) => o.scenario.id === outcome.scenario.id) ||
      candidates[0];
    if (!original) return null;
    const difference = outcome.loss_percent - original.loss_percent!;
    const changes = changed(original).map(
      (key) =>
        `${fields[key].label}: ${displayValue(key, original.scenario.settings[key]) ?? "off"} → ${displayValue(key, outcome.scenario.settings[key]) ?? "off"}`,
    );
    if (original.scenario.execution_seed !== outcome.scenario.execution_seed)
      changes.push("Execution seed changed");
    if (original.scenario.team_seed !== outcome.scenario.team_seed)
      changes.push("Team generation seed changed");
    return `${Math.abs(difference).toFixed(2)} percentage points ${difference < 0 ? "lower" : difference > 0 ? "higher" : "different"} than ${baseline.name} / ${original.scenario.name}. ${changes.length ? changes.join("; ") : "Identical settings and seeds"}. Observed difference; no causal or statistical significance claim.`;
  }

  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await work();
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  async function previewInputs() {
    if (!workspace || !taskSpec) return;
    const result = await api<Preview>(`${basePath}/editor`, "PUT", {
      expected_revision: workspace.revision,
      task_spec: taskSpec,
      definitions,
    });
    setPreview(result);
    setDirty(false);
    await load(workspace.id);
  }
  async function startManual() {
    if (!preview || !workspace) return;
    await api<Run>(`${basePath}/runs`, "POST", {
      request_id: crypto.randomUUID(),
      preview_digest: preview.digest,
      name: comparisonName,
      intent: "manual",
    });
    await load(workspace.id);
    setComparisonName("Comparison");
  }
  const editTasks = (value: TaskSpec) => {
    setTaskSpec(value);
    setDirty(true);
  };
  const editDefinitions = (value: Definition[]) => {
    setDefinitions(value);
    setDirty(true);
  };

  const flushInteractive = useCallback(async () => {
    const w = workspaceRef.current;
    if (
      !w ||
      !pending.current ||
      sending.current ||
      Date.now() - lastSent.current < 1050
    )
      return;
    const request = pending.current;
    sending.current = true;
    try {
      await api<Run>(`/api/v1/workspaces/${w.id}/runs`, "POST", request);
      if (pending.current === request) pending.current = null;
      lastSent.current = Date.now();
      setError(undefined);
      await load(w.id);
    } catch (e) {
      if (!(
        (e instanceof ApiError && ["RUN_ACTIVE"].includes(e.code)) ||
        (e instanceof ApiError &&
          e.code === "APP_CAPACITY" &&
          e.message.startsWith("Wait a moment"))
      )) {
        setError(e as Error);
        pending.current = null;
      }
    } finally {
      sending.current = false;
    }
  }, [load]);
  useEffect(() => {
    const timer = setInterval(() => {
      void flushInteractive();
    }, 450);
    return () => clearInterval(timer);
  }, [flushInteractive]);

  function commitInteractive(value = interactiveValue) {
    if (!baseline || !interactive) return;
    const key = JSON.stringify([baseline.id, property, effectiveFamily, value]);
    if (lastInteractive.current === key) return;
    lastInteractive.current = key;
    pending.current = {
      request_id: crypto.randomUUID(),
      preview_digest: "",
      name: `${fields[property].label}: ${displayValue(property, value) ?? "off"}`,
      intent: "interactive",
      source_run_id: baseline.id,
      property,
      value,
      family_value: JSON.parse(effectiveFamily),
    };
    void flushInteractive();
  }
  async function cancel() {
    pending.current = null;
    lastInteractive.current = "";
    setInteractive(false);
    clearTimeout(sliderTimer.current);
    if (active) {
      await api(`${basePath}/runs/${active.id}`, "DELETE");
      await load(workspace!.id);
    }
  }
  async function mutateComparison(run: Run, type: string) {
    await api(`${basePath}/runs/${run.id}/comparison`, "POST", {
      action: type,
    });
    await load(workspace!.id, type === "baseline");
  }
  function selectTab(index: number) {
    setTab(index);
    sessionStorage.setItem("value-stream-tab", String(index));
  }
  async function newWorkspace() {
    const w = await api<Workspace>("/api/v1/workspaces", "POST");
    localStorage.setItem("value-stream-workspace", w.id);
    location.href = `?workspace=${w.id}`;
  }

  if (!workspace || !taskSpec)
    return (
      <main className="startup">
        <span className="brand-symbol">↗</span>
        <h1>Value Stream</h1>
        <p>{error?.message || "Opening your simulation workspace…"}</p>
        {error && (
          <button onClick={() => void action(newWorkspace)}>
            Start a new workspace
          </button>
        )}
      </main>
    );
  const completed =
    active?.outcomes.filter((o) =>
      ["succeeded", "failed", "cancelled"].includes(o.status),
    ).length || 0;
  const best = successful
    .filter((o) => o.outcome.loss_percent != null)
    .sort((a, b) => a.outcome.loss_percent! - b.outcome.loss_percent!)[0];
  const totalModels = preview?.count;
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href={`?workspace=${workspace.id}`}>
          <span className="brand-symbol">↗</span>
          <span>
            VALUE STREAM<small>SIMULATION STUDIO</small>
          </span>
        </a>
        <div className="top-actions">
          <span className={`service-badge ${config?.ready ? "" : "offline"}`}>
            <i />
            {config?.ready ? "Simulation service ready" : "Service unavailable"}
          </span>
          <button
            className="text-button light"
            onClick={() => void action(newWorkspace)}
          >
            New workspace
          </button>
        </div>
      </header>
      <div className="intro">
        <div>
          <p className="eyebrow">EXPLORE YOUR DELIVERY SYSTEM</p>
          <h1>Find where value slips away.</h1>
          <p>
            Compare teams, release intervals, and capacity. Make the cost of
            delay visible.
          </p>
        </div>
        <span className="session-note">
          Temporary workspace
          <br />
          <strong>Saved until server shutdown</strong>
        </span>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          <div>
            <strong>
              {error instanceof ApiError
                ? error.code.replaceAll("_", " ")
                : "Something went wrong"}
            </strong>
            <p>{error.message}</p>
            {error instanceof ApiError && error.details != null && (
              <details>
                <summary>Details</summary>
                <pre>{JSON.stringify(error.details, null, 2)}</pre>
              </details>
            )}
          </div>
          <div>
            <button
              className="secondary"
              onClick={() =>
                void action(async () => {
                  await load(workspace.id, true);
                  setConfig(await api<Config>("/api/v1/config"));
                })
              }
            >
              Reload workspace
            </button>
            <button
              className="icon-button"
              aria-label="Dismiss error"
              onClick={() => setError(undefined)}
            >
              ×
            </button>
          </div>
        </div>
      )}
      {config && !config.ready && (
        <div className="notice">
          {config.error?.message} Retained comparisons remain available.{" "}
          <button
            onClick={() =>
              void action(async () => setConfig(await api("/api/v1/config")))
            }
          >
            Reconnect
          </button>
        </div>
      )}
      <main className="workspace-grid">
        <aside className="input-panel">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action(previewInputs);
            }}
          >
            <TaskEditor value={taskSpec} change={editTasks} />
            <ModelEditor definitions={definitions} change={editDefinitions} />
            <div className="launch-panel">
              <p className="hint">
                Up to {config?.limits.max_models ?? 100} models and{" "}
                {config?.limits.max_tasks ?? 1000} tasks per run.
              </p>
              <button
                className="secondary full"
                type="submit"
                disabled={busy || !!active}
              >
                Preview sweep
              </button>
              {preview && !dirty && (
                <div className="preview-box">
                  <strong>{totalModels} scenarios</strong>
                  <span> · one shared task set</span>
                  <details>
                    <summary>Review model combinations</summary>
                    <ul>
                      {preview.scenarios.map((s) => (
                        <li key={s.id}>{s.name}</li>
                      ))}
                    </ul>
                  </details>
                </div>
              )}
              <label className="field">
                <span>Comparison name</span>
                <input
                  value={comparisonName}
                  maxLength={120}
                  onChange={(e) => setComparisonName(e.target.value)}
                />
              </label>
              <button
                className="primary full"
                type="button"
                disabled={
                  busy || !!active || dirty || !preview || !comparisonName
                }
                onClick={() => void action(startManual)}
              >
                Run {totalModels || ""} scenarios <span aria-hidden>↗</span>
              </button>
              {dirty && (
                <p className="hint">Preview your inputs before running.</p>
              )}
            </div>
          </form>
        </aside>
        <section className="results-panel" aria-label="Simulation results">
          <div className="results-heading">
            <div>
              <p className="eyebrow">YOUR EXPERIMENT</p>
              <h2>Results & comparisons</h2>
            </div>
            <span className="pill">{workspace.runs.length} runs</span>
          </div>
          {active && (
            <div className="progress-card" role="status">
              <div>
                <strong>
                  {active.state === "reconnecting"
                    ? "Connection interrupted"
                    : active.state === "cancelling"
                      ? "Stopping the whole job…"
                      : "Updating comparison…"}
                </strong>
                <span>
                  {active.name} · {completed} of {active.outcomes.length} models
                  finished
                </span>
                <progress max={active.outcomes.length} value={completed} />
                {active.error && <p>{active.error.message}</p>}
              </div>
              {active.retry_paused && (
                <button
                  onClick={() =>
                    void action(async () => {
                      await api(`${basePath}/runs/${active.id}/resume`, "POST");
                    })
                  }
                >
                  Resume connection
                </button>
              )}
              <button className="secondary" onClick={() => void action(cancel)}>
                Cancel job
              </button>
            </div>
          )}
          <div className="stat-grid">
            <div className="stat">
              <span>Best observed value lost</span>
              <strong>{percent(best?.outcome.loss_percent)}</strong>
              <small>
                {best
                  ? `${best.run.name} · ${best.outcome.scenario.settings.team_size} developers`
                  : "Run a comparison to begin"}
              </small>
            </div>
            <div className="stat">
              <span>Scenarios shown</span>
              <strong>{outcomes.length.toString().padStart(2, "0")}</strong>
              <small>{successful.length} completed successfully</small>
            </div>
            <div className="stat">
              <span>Shared work</span>
              <strong>
                {workspace.task_spec.count}
                <em> tasks</em>
              </strong>
              <small>
                {(workspace.task_spec.depreciation_rate * 100).toFixed(2)}%
                depreciation / time unit
              </small>
            </div>
          </div>
          {!!workspace.runs.length && (
            <div className="comparison-list">
              {workspace.runs
                .filter((r) => r.task_set_id === selectedContext)
                .map((run) => (
                  <div
                    className={`comparison-chip ${selectedRuns.includes(run.id) ? "selected" : ""}`}
                    key={run.id}
                  >
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedRuns.includes(run.id)}
                        onChange={(e) =>
                          setSelectedRuns(
                            e.target.checked
                              ? [...selectedRuns, run.id]
                              : selectedRuns.filter((id) => id !== run.id),
                          )
                        }
                      />
                      <span>
                        {run.name}
                        <small>
                          {run.id === workspace.baseline_id
                            ? "BASELINE"
                            : run.pinned
                              ? "PINNED"
                              : run.state.replaceAll("_", " ")}
                        </small>
                      </span>
                    </label>
                    {terminal(run) && (
                      <>
                        <button
                          className="icon-button"
                          title={
                            run.pinned ? "Unpin comparison" : "Pin comparison"
                          }
                          aria-label={`${run.pinned ? "Unpin" : "Pin"} ${run.name}`}
                          onClick={() =>
                            void action(() =>
                              mutateComparison(
                                run,
                                run.pinned ? "unpin" : "pin",
                              ),
                            )
                          }
                        >
                          {run.pinned ? "◆" : "◇"}
                        </button>
                        <details className="comparison-menu">
                          <summary aria-label={`Actions for ${run.name}`}>
                            ⋯
                          </summary>
                          <button
                            onClick={() =>
                              void action(() =>
                                mutateComparison(run, "baseline"),
                              )
                            }
                          >
                            Use as baseline
                          </button>
                          <button
                            onClick={() =>
                              void action(() => mutateComparison(run, "delete"))
                            }
                          >
                            Delete comparison
                          </button>
                        </details>
                      </>
                    )}
                  </div>
                ))}
            </div>
          )}
          {baseline && (
            <section className="interactive-panel">
              <div className="interactive-title">
                <div>
                  <strong>What if?</strong>
                  <p className="hint">
                    Keep the baseline. Change one property to add a comparison.
                  </p>
                </div>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={interactive}
                    onChange={(e) => {
                      setInteractive(e.target.checked);
                      if (!e.target.checked) pending.current = null;
                    }}
                  />
                  Interactive mode
                </label>
              </div>
              {interactive && (
                <div className="interactive-controls">
                  <label className="field">
                    <span>Explore a property</span>
                    <select
                      value={property}
                      onChange={(e) => {
                        setProperty(e.target.value as keyof Settings);
                        setFamilyValue("");
                        setInteractiveValue(
                          e.target.value === "distribution" ? "linear" : 1,
                        );
                      }}
                    >
                      {Object.entries(fields)
                        .filter(
                          ([key]) =>
                            key !==
                            (tab === 0
                              ? "team_size"
                              : tab === 1
                                ? "deployment_cadence"
                                : ""),
                        )
                        .map(([key, f]) => (
                          <option value={key} key={key}>
                            {f.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Baseline value / family</span>
                    <select
                      value={effectiveFamily}
                      onChange={(e) => setFamilyValue(e.target.value)}
                    >
                      {familyValues.map((v) => (
                        <option key={v} value={v}>
                          {displayValue(property, JSON.parse(v)) ??
                            "Support disabled"}
                        </option>
                      ))}
                    </select>
                  </label>
                  {property === "distribution" ? (
                    <label className="field">
                      <span>New distribution</span>
                      <select
                        value={String(interactiveValue)}
                        onChange={(e) => {
                          setInteractiveValue(e.target.value);
                          commitInteractive(e.target.value);
                        }}
                      >
                        <option value="linear">Linear</option>
                        <option value="normal">Normal</option>
                      </select>
                    </label>
                  ) : (
                    <div className="slider-control">
                      <label className="field">
                        <span>New {fields[property].label.toLowerCase()}</span>
                        <input
                          aria-label="Interactive value"
                          type="number"
                          min={(fields[property].min ?? 0) * propertyScale}
                          max={
                            fields[property].max == null
                              ? undefined
                              : fields[property].max! * propertyScale
                          }
                          step={fields[property].step * propertyScale}
                          value={displayValue(property, interactiveValue) ?? ""}
                          placeholder="Disabled"
                          onChange={(e) =>
                            setInteractiveValue(
                              e.target.value === "" &&
                                property === "support_interval"
                                ? null
                                : e.target.valueAsNumber / propertyScale,
                            )
                          }
                          onBlur={() => commitInteractive()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitInteractive();
                          }}
                        />
                      </label>
                      <input
                        aria-label="Interactive slider"
                        type="range"
                        min={(fields[property].min ?? 0) * propertyScale}
                        max={
                          (fields[property].max ??
                            Math.max(20, Number(interactiveValue) || 0)) *
                          propertyScale
                        }
                        step={fields[property].step * propertyScale}
                        value={
                          Number(displayValue(property, interactiveValue)) || 0
                        }
                        onChange={(e) =>
                          setInteractiveValue(
                            Number(e.target.value) / propertyScale,
                          )
                        }
                        onPointerUp={(e) =>
                          commitInteractive(
                            Number(e.currentTarget.value) / propertyScale,
                          )
                        }
                        onKeyUp={(e) => {
                          const v =
                            Number(e.currentTarget.value) / propertyScale;
                          clearTimeout(sliderTimer.current);
                          sliderTimer.current = setTimeout(
                            () => commitInteractive(v),
                            400,
                          );
                        }}
                      />
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
          <div className="plot-card">
            <div className="plot-tabs" role="tablist" aria-label="Result plots">
              {tabs.map((label, i) => (
                <button
                  role="tab"
                  aria-selected={tab === i}
                  id={`tab-${i}`}
                  aria-controls="plot-panel"
                  tabIndex={tab === i ? 0 : -1}
                  key={label}
                  onClick={() => selectTab(i)}
                  onKeyDown={(e) => {
                    if (
                      ["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)
                    ) {
                      e.preventDefault();
                      const next =
                        e.key === "Home"
                          ? 0
                          : e.key === "End"
                            ? tabs.length - 1
                            : (i +
                                (e.key === "ArrowRight" ? 1 : -1) +
                                tabs.length) %
                              tabs.length;
                      selectTab(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="plot-tools">
              <label>
                Series limit{" "}
                <select
                  value={seriesLimit}
                  onChange={(e) => setSeriesLimit(Number(e.target.value))}
                >
                  {[6, 12, 24, 100].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              {tab >= 2 && (
                <label>
                  Detail selection{" "}
                  <select
                    value={detailSelection}
                    onChange={(e) => setDetailSelection(e.target.value)}
                  >
                    <option value="">First 12 selected scenarios</option>
                    {successful.map(({ run, outcome }) => (
                      <option
                        key={`${run.id}/${outcome.scenario.id}`}
                        value={`${run.id}/${outcome.scenario.id}`}
                      >
                        {run.name} · {outcome.scenario.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                className="text-button"
                onClick={() => setZoomRevision((v) => v + 1)}
              >
                Reset zoom
              </button>
            </div>
            <div role="tabpanel" id="plot-panel" aria-labelledby={`tab-${tab}`}>
              {outcomes.length ? (
                <Suspense
                  fallback={
                    <div className="empty-state">
                      Loading interactive plots…
                    </div>
                  }
                >
                  <Charts
                    runs={runs}
                    tab={tab}
                    details={detailViews}
                    context={`${selectedContext}-${zoomRevision}`}
                    maxSeries={seriesLimit}
                  />
                </Suspense>
              ) : (
                <div className="empty-state">
                  <div className="empty-chart" aria-hidden>
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                  <h3>Your next insight starts with a comparison.</h3>
                  <p>
                    Choose your task set and model sweeps, preview the
                    combinations,
                    <br />
                    then run your first experiment.
                  </p>
                </div>
              )}
            </div>
          </div>
          {!!successful.length && (
            <section className="insights">
              <div className="section-heading">
                <span className="step">↗</span>
                <h2>What the results suggest</h2>
              </div>
              {detailViews.slice(0, 1).flatMap((item) =>
                item.view.observations.map((observation) => (
                  <article key={observation.rule + observation.evidence}>
                    <div>
                      <strong>{observation.message}</strong>
                      <p>{observation.evidence}</p>
                    </div>
                    {observation.property && (
                      <button
                        className="secondary"
                        onClick={() => {
                          setInteractive(true);
                          setProperty(observation.property as keyof Settings);
                          setFamilyValue(
                            JSON.stringify(
                              item.outcome.scenario.settings[
                                observation.property as keyof Settings
                              ],
                            ),
                          );
                          setInteractiveValue(observation.value);
                        }}
                      >
                        Prepare comparison
                      </button>
                    )}
                  </article>
                )),
              )}
              <p className="hint">
                Suggested changes are untested. Enable the controls above and
                commit a value to run a comparison.
              </p>
            </section>
          )}
          {!!outcomes.length && (
            <section className="table-card">
              <div className="table-heading">
                <h2>Scenario results</h2>
                <div className="export-controls">
                  <label className="sr-only" htmlFor="export-run">
                    Comparison to export
                  </label>
                  <select
                    id="export-run"
                    value={exportRun}
                    onChange={(e) => setExportRun(e.target.value)}
                  >
                    {workspace.runs
                      .filter(terminal)
                      .filter((r) => r.task_set_id === selectedContext)
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                  </select>
                  {["summary", "events", "resources"].map((kind) => (
                    <a
                      key={kind}
                      className={!exportRun ? "disabled" : ""}
                      href={`${basePath}/runs/${exportRun}/exports/${kind}`}
                      download
                    >
                      {kind} CSV ↓
                    </a>
                  ))}
                </div>
              </div>
              <div className="table-scroll">
                <table>
                  <caption className="sr-only">
                    Scenario summaries for selected comparisons. Loss is a
                    positive percentage of initial value.
                  </caption>
                  <thead>
                    <tr>
                      <th>Scenario</th>
                      <th>Team</th>
                      <th>Interval</th>
                      <th>Value lost</th>
                      <th>Completion time</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outcomes.map(({ run, outcome: o }) => (
                      <tr key={`${run.id}/${o.scenario.id}`}>
                        <td>
                          <strong>{run.name}</strong>
                          <small>{o.scenario.name}</small>
                        </td>
                        <td>{o.scenario.settings.team_size}</td>
                        <td>
                          {o.scenario.settings.deployment_cadence ||
                            "Continuous"}
                        </td>
                        <td>
                          {percent(o.loss_percent)}
                          {baselineDifference(run, o) && (
                            <details>
                              <summary>Baseline comparison</summary>
                              <p>{baselineDifference(run, o)}</p>
                            </details>
                          )}
                        </td>
                        <td>{o.completion_time?.toFixed(2) ?? "—"}</td>
                        <td>
                          <span className={`status status-${o.status}`}>
                            {o.status}
                            {o.cached ? " · reused" : ""}
                          </span>
                          {o.error && (
                            <details>
                              <summary>Error details</summary>
                              <p>
                                {o.error.code}: {o.error.message}
                              </p>
                            </details>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {tab >= 2 && detailViews.length > 0 && (
            <details className="metric-table">
              <summary>Accessible plot data</summary>
              {detailViews.map(({ run, outcome, view }) => (
                <div key={run.id + outcome.scenario.id}>
                  <h3>
                    {run.name} · {outcome.scenario.name}
                  </h3>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          {(tab === 2
                            ? ["Stage", "Mean loss (%)", "Visits"]
                            : tab === 3
                              ? [
                                  "Stage",
                                  "Category",
                                  "Recorded duration",
                                  "Activity share (%)",
                                ]
                              : ["Stage", "Time", "Waiting requests"]
                          ).map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {tab === 2
                          ? view.metrics.stages.map((s) => (
                              <tr key={s.stage}>
                                <td>{s.label}</td>
                                <td>{s.loss_percent.toFixed(2)}</td>
                                <td>{s.visits}</td>
                              </tr>
                            ))
                          : tab === 3
                            ? view.metrics.activity.flatMap((s) =>
                                Object.keys(s.durations).map((k) => (
                                  <tr key={s.stage + k}>
                                    <td>{s.label}</td>
                                    <td>{k}</td>
                                    <td>{s.durations[k].toFixed(2)}</td>
                                    <td>{percent(s.shares[k])}</td>
                                  </tr>
                                )),
                              )
                            : view.metrics.backlog.flatMap((s) =>
                                s.time.slice(0, 100).map((t, i) => (
                                  <tr key={s.stage + i}>
                                    <td>{s.label}</td>
                                    <td>{t.toFixed(2)}</td>
                                    <td>{s.waiting[i]}</td>
                                  </tr>
                                )),
                              )}
                      </tbody>
                    </table>
                  </div>
                  {tab === 4 && (
                    <p className="hint">
                      First 100 displayed points per stage. Export resource
                      history for all observations.
                    </p>
                  )}
                </div>
              ))}
            </details>
          )}
          <footer className="workspace-footer">
            Built for exploration. One seeded run per scenario.{" "}
            <button
              className="text-button"
              disabled={!!active}
              onClick={() =>
                void action(async () => {
                  await api(basePath, "DELETE");
                  localStorage.removeItem("value-stream-workspace");
                  location.href = "/";
                })
              }
            >
              Delete workspace
            </button>
          </footer>
        </section>
      </main>
    </div>
  );
}
