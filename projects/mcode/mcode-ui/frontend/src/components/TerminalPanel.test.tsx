import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TerminalPanel } from "./TerminalPanel";

describe("TerminalPanel", () => {
  it("renders runtime selector and updates python", () => {
    const updates: Array<{ python?: string; shell?: string }> = [];
    render(
      <TerminalPanel
        jobs={[]}
        runtime={{
          shell: "/bin/zsh",
          python: "/Applications/anaconda3/bin/python",
          python_source: "conda",
          candidates: [
            {
              path: "/Applications/anaconda3/bin/python",
              label: "Conda base",
              source: "conda",
              selected: true,
            },
            {
              path: "/usr/bin/python3",
              label: "python3 on PATH",
              source: "system",
              selected: false,
            },
          ],
        }}
        onRuntimeChange={(patch) => updates.push(patch)}
      />,
    );

    fireEvent.change(screen.getByLabelText("Python"), { target: { value: "/usr/bin/python3" } });
    expect(updates).toEqual([{ python: "/usr/bin/python3" }]);
    expect(screen.getByText(/Anaconda|anaconda3/)).toBeTruthy();
  });

  it("shows python jobs", () => {
    render(
      <TerminalPanel
        jobs={[{ job_id: "python-1", kind: "python", path: "/tmp/python-1.log", updated_at: 1, tail: "OK" }]}
        runtime={null}
      />,
    );
    expect(screen.getByText("python-1")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
  });
});
