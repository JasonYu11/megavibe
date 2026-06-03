import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestDock } from "./TestDock";

describe("TestDock", () => {
  afterEach(() => cleanup());

  it("shows running test state", () => {
    render(
      <TestDock
        onRun={vi.fn()}
        run={{ id: "t1", label: "subagent", command: ["python3"], status: "running", started_at: 1, finished_at: 0, exit_code: null, output: "" }}
      />,
    );
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("runs product acceptance, subagent, and benchmark actions", () => {
    const onRun = vi.fn();
    render(<TestDock onRun={onRun} run={null} />);
    fireEvent.click(screen.getByText("产品验收"));
    fireEvent.click(screen.getByText("子测试"));
    fireEvent.click(screen.getByText("回归规格"));
    fireEvent.click(screen.getByText("8项回归"));
    expect(onRun).toHaveBeenNthCalledWith(1, "product");
    expect(onRun).toHaveBeenNthCalledWith(2, "subagent");
    expect(onRun).toHaveBeenNthCalledWith(3, "benchmark-dry");
    expect(onRun).toHaveBeenNthCalledWith(4, "benchmark");
  });
});
