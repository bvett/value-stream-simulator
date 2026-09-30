import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { ModelEditor, TaskEditor } from "./editors";
import type { Definition, TaskSpec } from "./types";
afterEach(cleanup);
const definition: Definition = {
  id: "model",
  name: "Example",
  revision: 1,
  team_seed: 123,
  execution_seed: 456,
  sweeps: {},
  settings: {
    team_size: 4,
    efficiency_min: 0.5,
    efficiency_max: 1.5,
    distribution: "linear",
    deployment_cadence: 5,
    qa_size: 2,
    qa_time_cost: 0.1,
    qa_failure_rate: 0,
    qa_failure_cost: 0,
    toolchain_size: 1,
    deployment_duration: 0.25,
    deployment_failure_rate: 0,
    support_interval: null,
    support_task_story_points: 1,
  },
};
describe("input behavior", () => {
  it("changes team size into a multi-value sweep and supports duplication", () => {
    function Fixture() {
      const [definitions, set] = useState([definition]);
      return (
        <>
          <ModelEditor definitions={definitions} change={set} />
          <output>{JSON.stringify(definitions)}</output>
        </>
      );
    }
    render(<Fixture />);
    fireEvent.change(screen.getByLabelText("Team size mode"), {
      target: { value: "list" },
    });
    fireEvent.blur(screen.getByLabelText("Team size values"), {
      target: { value: "2, 4, 6" },
    });
    expect(screen.getByRole("status").textContent).toContain(
      '"team_size":[2,4,6]',
    );
    fireEvent.click(screen.getByRole("button", { name: "Duplicate Example" }));
    expect(screen.getAllByLabelText("Model name")).toHaveLength(2);
  });
  it("converts fixed and swept percentage rates to API fractions", () => {
    function Fixture() {
      const [definitions, set] = useState([definition]);
      return (
        <>
          <ModelEditor definitions={definitions} change={set} />
          <output>{JSON.stringify(definitions)}</output>
        </>
      );
    }
    render(<Fixture />);
    fireEvent.change(screen.getByLabelText("QA failure rate (%)"), {
      target: { value: "25" },
    });
    expect(screen.getByRole("status").textContent).toContain(
      '"qa_failure_rate":0.25',
    );
    fireEvent.change(screen.getByLabelText("QA failure rate (%) mode"), {
      target: { value: "list" },
    });
    fireEvent.blur(screen.getByLabelText("QA failure rate (%) values"), {
      target: { value: "5, 10, 25" },
    });
    expect(screen.getByRole("status").textContent).toContain(
      '"qa_failure_rate":[0.05,0.1,0.25]',
    );
  });
  it("displays depreciation as percent and saves its fractional value", () => {
    function Fixture() {
      const [spec, set] = useState<TaskSpec>({
        name: "Tasks",
        count: 100,
        story_points: { kind: "constant", value: 1 },
        initial_value: { kind: "constant", value: 1 },
        depreciation_rate: 0.005,
        seed: 42,
      });
      return (
        <>
          <TaskEditor value={spec} change={set} />
          <output>{JSON.stringify(spec)}</output>
        </>
      );
    }
    render(<Fixture />);
    fireEvent.change(screen.getByLabelText("Depreciation per time unit (%)"), {
      target: { value: "2" },
    });
    expect(screen.getByRole("status").textContent).toContain(
      '"depreciation_rate":0.02',
    );
    fireEvent.change(screen.getByLabelText("Story points mode"), {
      target: { value: "uniform" },
    });
    expect(screen.getByLabelText("Story points minimum")).toBeTruthy();
  });
});
