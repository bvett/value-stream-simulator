import type { Definition, Settings, TaskSpec } from "./types";

export const fields: Record<
  keyof Settings,
  { label: string; help: string; step: number; min?: number; max?: number }
> = {
  team_size: {
    label: "Team size",
    help: "Number of developers",
    step: 1,
    min: 1,
  },
  efficiency_min: {
    label: "Minimum efficiency",
    help: "Story points per time unit",
    step: 0.1,
    min: 0,
  },
  efficiency_max: {
    label: "Maximum efficiency",
    help: "Story points per time unit",
    step: 0.1,
    min: 0,
  },
  distribution: {
    label: "Efficiency distribution",
    help: "Linear spans both bounds at each team size; normal uses bounded random draws.",
    step: 1,
  },
  deployment_cadence: {
    label: "Deployment interval",
    help: "Time units; 0 means continuous",
    step: 1,
    min: 0,
  },
  qa_size: {
    label: "QA pool size",
    help: "Concurrent testers",
    step: 1,
    min: 1,
  },
  qa_time_cost: {
    label: "QA time per story point",
    help: "Time units per story point",
    step: 0.05,
    min: 0,
  },
  qa_failure_rate: {
    label: "QA failure rate (%)",
    help: "Percent from 0 to 100",
    step: 0.05,
    min: 0,
    max: 1,
  },
  qa_failure_cost: {
    label: "QA rework (%)",
    help: "Percent of original effort to repeat",
    step: 0.05,
    min: 0,
    max: 1,
  },
  toolchain_size: {
    label: "Deployment pool size",
    help: "Concurrent deployments",
    step: 1,
    min: 1,
  },
  deployment_duration: {
    label: "Deployment duration",
    help: "Simulation time units",
    step: 0.25,
    min: 0,
  },
  deployment_failure_rate: {
    label: "Deployment failure rate (%)",
    help: "Percent from 0 to 100",
    step: 0.05,
    min: 0,
    max: 1,
  },
  support_interval: {
    label: "Support interval",
    help: "Time between support tasks; blank disables support",
    step: 1,
    min: 0,
  },
  support_task_story_points: {
    label: "Support task effort",
    help: "Story points per support task",
    step: 0.25,
    min: 0,
  },
};

export function fieldScale(name: keyof Settings) {
  return [
    "qa_failure_rate",
    "qa_failure_cost",
    "deployment_failure_rate",
  ].includes(name)
    ? 100
    : 1;
}
export function displayValue(
  name: keyof Settings,
  value: number | string | null | undefined,
) {
  return typeof value === "number"
    ? Number((value * fieldScale(name)).toPrecision(12))
    : value;
}

function NumberField({
  label,
  value,
  change,
  step = 1,
  min = 0,
  max,
}: {
  label: string;
  value: number;
  change: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => change(e.target.valueAsNumber)}
        required
      />
    </label>
  );
}
export function TaskEditor({
  value,
  change,
}: {
  value: TaskSpec;
  change: (v: TaskSpec) => void;
}) {
  const set = (key: keyof TaskSpec, next: unknown) =>
    change({ ...value, [key]: next });
  const quantity = (key: "story_points" | "initial_value", label: string) => {
    const v = value[key];
    return (
      <fieldset className="quantity">
        <legend>{label}</legend>
        <select
          aria-label={`${label} mode`}
          value={v.kind}
          onChange={(e) =>
            set(
              key,
              e.target.value === "uniform"
                ? { kind: "uniform", minimum: 0.5, maximum: 2 }
                : { kind: "constant", value: 1 },
            )
          }
        >
          <option value="constant">Constant</option>
          <option value="uniform">Uniform range</option>
        </select>
        {v.kind === "constant" ? (
          <NumberField
            label={`${label} value`}
            value={v.value}
            step={0.1}
            change={(next) => set(key, { ...v, value: next })}
          />
        ) : (
          <div className="two-col">
            <NumberField
              label={`${label} minimum`}
              value={v.minimum}
              step={0.1}
              change={(next) => set(key, { ...v, minimum: next })}
            />
            <NumberField
              label={`${label} maximum`}
              value={v.maximum}
              step={0.1}
              change={(next) => set(key, { ...v, maximum: next })}
            />
          </div>
        )}
      </fieldset>
    );
  };
  return (
    <div className="editor-section">
      <div className="section-heading">
        <span className="step">01</span>
        <h2>Define the work</h2>
      </div>
      <p className="muted">Every scenario receives this same set of tasks.</p>
      <label className="field">
        <span>Task-set name</span>
        <input
          value={value.name}
          maxLength={120}
          onChange={(e) => set("name", e.target.value)}
        />
      </label>
      <NumberField
        label="Task count"
        value={value.count}
        min={1}
        change={(v) => set("count", v)}
      />
      {quantity("story_points", "Story points")}
      {quantity("initial_value", "Initial value")}
      <NumberField
        label="Depreciation per time unit (%)"
        value={value.depreciation_rate * 100}
        step={0.1}
        max={100}
        change={(v) => set("depreciation_rate", v / 100)}
      />
      <details>
        <summary>Reproducibility</summary>
        <NumberField
          label="Task generation seed"
          value={value.seed}
          change={(v) => set("seed", v)}
        />
        <button
          className="text-button"
          type="button"
          onClick={() => set("seed", Math.floor(Math.random() * 1e9))}
        >
          Regenerate task set
        </button>
        <p className="hint">
          A new seed starts a separate comparison context when saved.
        </p>
      </details>
    </div>
  );
}

function SweepField({
  name,
  definition,
  change,
}: {
  name: keyof Settings;
  definition: Definition;
  change: (v: Definition) => void;
}) {
  const info = fields[name],
    axis = definition.sweeps[name];
  const mode =
    axis === undefined ? "fixed" : Array.isArray(axis) ? "list" : "range";
  const updateAxis = (next: typeof axis | undefined) => {
    const sweeps = { ...definition.sweeps };
    if (next === undefined) delete sweeps[name];
    else sweeps[name] = next;
    change({ ...definition, sweeps });
  };
  const fixed = definition.settings[name];
  const scale = fieldScale(name);
  return (
    <fieldset className="sweep-field">
      <legend>{info.label}</legend>
      <div className="sweep-row">
        <select
          aria-label={`${info.label} mode`}
          value={mode}
          onChange={(e) =>
            updateAxis(
              e.target.value === "fixed"
                ? undefined
                : e.target.value === "list"
                  ? [fixed]
                  : {
                      start: Number(fixed) || 1,
                      end: (Number(fixed) || 1) + 2 * info.step,
                      step: info.step,
                    },
            )
          }
        >
          <option value="fixed">Fixed</option>
          <option value="list">Sweep: list</option>
          {name !== "distribution" && (
            <option value="range">Sweep: range</option>
          )}
        </select>
        {mode === "fixed" &&
          (name === "distribution" ? (
            <select
              aria-label={info.label}
              value={String(fixed)}
              onChange={(e) =>
                change({
                  ...definition,
                  settings: {
                    ...definition.settings,
                    distribution: e.target.value as "linear" | "normal",
                  },
                })
              }
            >
              <option value="linear">Linear</option>
              <option value="normal">Normal</option>
            </select>
          ) : (
            <input
              aria-label={info.label}
              type="number"
              step={info.step * scale}
              min={info.min == null ? undefined : info.min * scale}
              max={info.max == null ? undefined : info.max * scale}
              value={displayValue(name, fixed) ?? ""}
              placeholder={name === "support_interval" ? "Disabled" : ""}
              onChange={(e) =>
                change({
                  ...definition,
                  settings: {
                    ...definition.settings,
                    [name]:
                      e.target.value === "" && name === "support_interval"
                        ? null
                        : e.target.valueAsNumber / scale,
                  },
                })
              }
            />
          ))}
        {mode === "list" && (
          <input
            aria-label={`${info.label} values`}
            defaultValue={(axis as (number | string | null)[])
              .map((v) => displayValue(name, v) ?? "off")
              .join(", ")}
            key={`${definition.id}-${name}-list`}
            onBlur={(e) => {
              const parts = e.target.value.split(",").map((s) => s.trim());
              updateAxis(
                parts.map((s) =>
                  name === "distribution"
                    ? s
                    : s === "off"
                      ? null
                      : Number(s) / scale,
                ),
              );
            }}
            placeholder="2, 4, 6"
          />
        )}
      </div>
      {mode === "range" && !Array.isArray(axis) && axis && (
        <div className="three-col">
          {(["start", "end", "step"] as const).map((key) => (
            <label className="field" key={key}>
              <span>{key}</span>
              <input
                aria-label={`${info.label} ${key}`}
                type="number"
                step={info.step * scale}
                value={displayValue(name, axis[key]) ?? ""}
                onChange={(e) =>
                  updateAxis({ ...axis, [key]: e.target.valueAsNumber / scale })
                }
              />
            </label>
          ))}
        </div>
      )}
      <p className="hint">{info.help}</p>
    </fieldset>
  );
}
export function ModelEditor({
  definitions,
  change,
}: {
  definitions: Definition[];
  change: (v: Definition[]) => void;
}) {
  const set = (i: number, next: Definition) =>
    change(
      definitions.map((v, index) =>
        index === i ? { ...next, revision: v.revision + 1 } : v,
      ),
    );
  const core = [
    "team_size",
    "efficiency_min",
    "efficiency_max",
    "distribution",
    "deployment_cadence",
  ] as const;
  return (
    <div className="editor-section">
      <div className="section-heading">
        <span className="step">02</span>
        <h2>Shape the delivery system</h2>
      </div>
      <p className="muted">
        Sweep several properties to explore every combination.
      </p>
      {definitions.map((d, i) => (
        <article className="model-card" key={d.id}>
          <div className="model-title">
            <label className="field">
              <span>Model name</span>
              <input
                value={d.name}
                maxLength={120}
                onChange={(e) => set(i, { ...d, name: e.target.value })}
              />
            </label>
            <button
              title="Duplicate model"
              aria-label={`Duplicate ${d.name}`}
              type="button"
              className="icon-button"
              onClick={() =>
                change([
                  ...definitions,
                  {
                    ...structuredClone(d),
                    id: crypto.randomUUID(),
                    name: `${d.name} copy`.slice(0, 120),
                    revision: 1,
                  },
                ])
              }
            >
              ＋
            </button>
            {definitions.length > 1 && (
              <button
                className="icon-button"
                type="button"
                aria-label={`Remove ${d.name}`}
                onClick={() => change(definitions.filter((_, j) => i !== j))}
              >
                ×
              </button>
            )}
          </div>
          {core.map((key) => (
            <SweepField
              key={key}
              name={key}
              definition={d}
              change={(v) => set(i, v)}
            />
          ))}
          <details>
            <summary>QA, deployment & support</summary>
            {(Object.keys(fields) as (keyof Settings)[])
              .filter((key) => !(core as readonly string[]).includes(key))
              .map((key) => (
                <SweepField
                  key={key}
                  name={key}
                  definition={d}
                  change={(v) => set(i, v)}
                />
              ))}
          </details>
          <details>
            <summary>Team & execution seeds</summary>
            <NumberField
              label="Team generation seed"
              value={d.team_seed}
              change={(v) => set(i, { ...d, team_seed: v })}
            />
            <NumberField
              label="Execution seed"
              value={d.execution_seed}
              change={(v) => set(i, { ...d, execution_seed: v })}
            />
          </details>
        </article>
      ))}
    </div>
  );
}
