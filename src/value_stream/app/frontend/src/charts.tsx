import { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js/dist/plotly-basic.min.js";
import type { Data, Layout } from "plotly.js";
import type { Run, ResultView, Outcome } from "./types";
// Serialize Plotly updates and replace pending work with the newest view. Plotly
// mutates its inputs, so each render receives fresh copies of the chart description.
function PlotSurface({
  data,
  layout,
  tab,
  onRendered,
  onError,
}: {
  data: Data[];
  layout: Partial<Layout>;
  tab: number;
  onRendered: (tab: number) => void;
  onError: (error: string) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const queue = useRef({
    pending: "",
    busy: false,
    disposed: false,
    revision: "",
  });
  const callbacks = useRef({ onRendered, onError });
  callbacks.current = { onRendered, onError };
  const description = JSON.stringify({ data, layout, tab });
  useEffect(() => {
    const state = queue.current;
    state.disposed = false;
    const target = element.current;
    return () => {
      state.disposed = true;
      if (!state.busy && target) Plotly.purge(target);
    };
  }, []);
  useEffect(() => {
    const state = queue.current;
    const target = element.current!;
    state.pending = description;
    if (state.busy) return;
    state.busy = true;
    void (async () => {
      while (state.pending && !state.disposed) {
        const next = JSON.parse(state.pending);
        state.pending = "";
        try {
          const render =
            state.revision === next.layout.uirevision
              ? Plotly.react
              : Plotly.newPlot;
          await render(target, next.data, next.layout, {
            responsive: false,
            displaylogo: false,
            scrollZoom: true,
            modeBarButtonsToRemove: ["lasso2d", "select2d"],
            toImageButtonOptions: { format: "png", filename: "value-stream" },
          });
          state.revision = next.layout.uirevision;
          if (!state.disposed && !state.pending)
            callbacks.current.onRendered(next.tab);
        } catch (error) {
          if (!state.disposed) callbacks.current.onError(String(error));
        }
      }
      state.busy = false;
      if (state.disposed) Plotly.purge(target);
    })();
  }, [description]);
  return <div ref={element} style={{ width: "100%" }} />;
}
export const tabs = [
  "Value lost / team size",
  "Value lost / deployment interval",
  "Mean stage loss",
  "Resource utilization",
  "Resource backlog",
];
const palette = [
  "#0e766e",
  "#d77938",
  "#496ba6",
  "#a0588b",
  "#65974e",
  "#9b803a",
  "#675ba6",
  "#337a91",
];
const colors = new Map<string, string>();
export function color(id: string) {
  if (!colors.has(id)) colors.set(id, palette[colors.size % palette.length]);
  return colors.get(id)!;
}
const value = (n: number | null | undefined) =>
  n == null ? "N/A" : `${n.toFixed(2)}%`;
export { value as percent };

export function summaryTraces(
  runs: Run[],
  axis: "team_size" | "deployment_cadence",
): Data[] {
  const result: Data[] = [];
  for (const [runIndex, run] of runs.entries()) {
    const groups = new Map<string, Outcome[]>();
    for (const outcome of run.outcomes) {
      const { settings, definition_id, team_seed } = outcome.scenario;
      const group = JSON.stringify([
        definition_id,
        team_seed,
        Object.entries(settings).filter(([key]) => key !== axis),
      ]);
      groups.set(group, [...(groups.get(group) || []), outcome]);
    }
    for (const [group, outcomes] of groups) {
      outcomes.sort(
        (a, b) => a.scenario.settings[axis] - b.scenario.settings[axis],
      );
      const s = outcomes[0].scenario.settings;
      const differences = Object.keys(s)
        .filter(
          (key) =>
            key !== axis &&
            new Set(
              run.outcomes.map((o) =>
                JSON.stringify(o.scenario.settings[key as keyof typeof s]),
              ),
            ).size > 1,
        )
        .map((key) => `${key.replaceAll("_", " ")} ${s[key as keyof typeof s]}`)
        .join(", ");
      const name = `${run.name} · ${outcomes[0].scenario.name.split(" · ")[0]} · ${axis === "team_size" ? `interval ${s.deployment_cadence}` : `team ${s.team_size}`} · QA ${s.qa_size}${differences ? ` · ${differences}` : ""}`;
      result.push({
        uid: `${run.id}-${outcomes[0].scenario.id}`,
        x: outcomes.map((o) => o.scenario.settings[axis]),
        y: outcomes.map((o) =>
          o.status === "succeeded" ? o.loss_percent : null,
        ),
        text: outcomes.map((o) => `${o.scenario.name}<br>${o.status}`),
        name,
        type: "scatter",
        mode: outcomes.length > 1 ? "lines+markers" : "markers",
        connectgaps: false,
        line: {
          color: color(run.id + group),
          width: 2.5,
          dash: runIndex % 2 ? "dash" : "solid",
        },
        marker: { size: 8 },
        hovertemplate: "%{text}<br>Value lost: %{y:.2f}%<extra></extra>",
      });
    }
  }
  return result;
}

export function Charts({
  runs,
  tab,
  details,
  context,
  maxSeries = 12,
}: {
  runs: Run[];
  tab: number;
  details: { run: Run; outcome: Outcome; view: ResultView }[];
  context: string;
  maxSeries?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [renderedTab, setRenderedTab] = useState(-1);
  const [plotError, setPlotError] = useState("");
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let frame = 0;
    const observer = new ResizeObserver((entries) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() =>
        setWidth(Math.max(260, Math.round(entries[0].contentRect.width))),
      );
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);
  let traces: Data[] = [];
  let xTitle = "",
    yTitle = "",
    note = "";

  const yType = "-";

  if (tab < 2) {
    const axis = tab === 0 ? "team_size" : "deployment_cadence";
    traces = summaryTraces(runs, axis);
    xTitle =
      tab === 0
        ? "Developers in team"
        : "Deployment interval (time units; 0 = continuous)";
    yTitle = "Value lost (%)";
    note =
      "Lower is better. One seeded simulation per scenario; differences are observations, not estimates of statistical significance.";
  } else if (tab === 2) {
    traces = details.map(({ run, outcome, view }) => ({
      type: "bar",
      name: `${run.name} · team ${outcome.scenario.settings.team_size}`,
      x: view.metrics.stages.map((s) => s.label),
      y: view.metrics.stages.map((s) => s.loss_percent),
      marker: { color: color(run.id + outcome.scenario.id) },
      text: view.metrics.stages.map((s) => `${s.visits} stage visits`),
      hovertemplate:
        "%{x}<br>%{y:.2f}% · %{text}<extra>%{fullData.name}</extra>",
    }));
    xTitle = "Workflow stage";
    yTitle = "Mean stage-visit loss (%)";
    note =
      "Equal weighting of completed development-task stage visits, including rework and failures. These means do not add up to overall value lost.";
  } else if (tab === 3) {
    const categories = [
      ["idle_t", "Recorded idle"],
      ["success_t", "Successful work"],
      ["failure_t", "Failed work"],
      ["interruption_t", "Interruption duration"],
    ];
    traces = categories.map(([key, label], i) => ({
      type: "bar",
      name: label,
      x: details.flatMap((d) =>
        d.view.metrics.activity.map(
          (a) =>
            `${d.run.name} · team ${d.outcome.scenario.settings.team_size}<br>${a.label}`,
        ),
      ),
      y: details.flatMap((d) =>
        d.view.metrics.activity.map((a) => a.shares[key]),
      ),
      marker: { color: palette[i] },
      text: details.flatMap((d) =>
        d.view.metrics.activity.map(
          (a) => `${a.durations[key].toFixed(2)} recorded time units`,
        ),
      ),
      hovertemplate: "%{text}<br>%{y:.2f}%<extra>%{fullData.name}</extra>",
    }));
    yTitle = "Recorded activity share (%)";
    note =
      "Recorded activity share, not total capacity utilization. Durations can overlap during interruptions and exclude unrecorded unused capacity.";
  } else {
    traces = details.flatMap(({ run, outcome, view }) =>
      view.metrics.backlog.map((b) => ({
        type: "scatter" as const,
        mode: "lines" as const,
        name: `${run.name} · team ${outcome.scenario.settings.team_size} · ${b.label}`,
        x: b.time,
        y: b.waiting,
        line: {
          shape: "hv" as const,
          color: color(run.id + outcome.scenario.id + b.stage),
        },
        hovertemplate:
          "Time %{x}<br>%{y} waiting requests<extra>%{fullData.name}</extra>",
      })),
    );
    xTitle = "Simulation time";
    yTitle = "Waiting resource requests";

    note =
      "Requests may contain batches of tasks. This excludes waiting for a deployment interval before requesting a resource.";
    if (details.some((d) => d.view.metrics.backlog.some((b) => b.reduced)))
      note += " Reduced-resolution display; CSV exports retain all events.";
  }
  const total = traces.length;
  if (tab !== 3) traces = traces.slice(0, maxSeries);
  const layout: Partial<Layout> = {
    autosize: false,
    width,
    height: 440,
    paper_bgcolor: "transparent",
    plot_bgcolor: "#fff",
    font: {
      family: "Inter, ui-sans-serif, system-ui",
      color: "#405653",
      size: 12,
    },
    margin: { l: 65, r: 24, t: 20, b: 85 },
    xaxis: {
      title: { text: xTitle },
      gridcolor: "#edf1ec",
      zerolinecolor: "#c7d3cb",
      automargin: true,
    },
    yaxis: {
      title: { text: yTitle },
      gridcolor: "#edf1ec",
      rangemode: "tozero",
      automargin: true,
      type: yType,
    },
    legend: { orientation: "h", y: -0.28, font: { size: 11 } },
    barmode: tab === 3 ? "stack" : "group",
    uirevision: `${context}-${tab}`,
  };
  return (
    <>
      <div
        ref={container}
        className="chart"
        aria-label={tabs[tab]}
        data-rendered-tab={renderedTab}
      >
        <PlotSurface
          data={traces}
          layout={layout}
          tab={tab}
          onRendered={(rendered) => {
            setRenderedTab(rendered);
            setPlotError("");
          }}
          onError={setPlotError}
        />
      </div>
      {plotError && (
        <p role="alert">
          Plot could not update: {plotError}. The result table remains
          available.
        </p>
      )}
      <p className="chart-note">{note}</p>
      {total > maxSeries && tab !== 3 && (
        <p className="hint">
          Showing {maxSeries} of {total} series. Increase the series limit or
          select fewer comparisons.
        </p>
      )}
    </>
  );
}
