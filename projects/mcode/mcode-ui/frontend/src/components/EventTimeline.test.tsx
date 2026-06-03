import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EventTimeline } from "./EventTimeline";

describe("EventTimeline", () => {
  afterEach(() => cleanup());

  it("renders unknown event kinds", () => {
    const view = render(<EventTimeline events={[{ kind: "new_future_event", data: { subagent_id: "sub-1" } }]} />);
    fireEvent.click(within(view.container).getByText(/显示调试事件/));
    expect(screen.getByText("new_future_event")).toBeInTheDocument();
    expect(screen.getByText(/sub-1/)).toBeInTheDocument();
  });

  it("compacts command output events", () => {
    const view = render(
      <EventTimeline
        events={[
          { kind: "command_output", data: { command_id: "cmd-1", text: "a\n" }, seq: 1 },
          { kind: "command_output", data: { command_id: "cmd-1", text: "b\n" }, seq: 2 },
          { kind: "command_finished", data: { command_id: "cmd-1", exit_code: 0 }, seq: 3 },
        ]}
      />,
    );
    fireEvent.click(within(view.container).getByText(/显示调试事件/));
    expect(screen.getAllByText("command_output")).toHaveLength(1);
    expect(screen.getByText("2 条")).toBeInTheDocument();
    expect(screen.getByText(/a\\nb/)).toBeInTheDocument();
  });

  it("hides debug events by default", () => {
    render(<EventTimeline events={[{ kind: "compact_check", data: { chars: 10 }, seq: 1 }]} />);
    expect(screen.queryByText("compact_check")).not.toBeInTheDocument();
    expect(screen.getByText(/显示调试事件/)).toBeInTheDocument();
  });

  it("filters events by kind", () => {
    render(
      <EventTimeline
        events={[
          { kind: "tool_dispatch", data: { name: "read_file" }, seq: 1 },
          { kind: "assistant_message", data: { content: "ok" }, seq: 2 },
        ]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Filter event kind"), { target: { value: "tool" } });
    expect(screen.getByText("tool_dispatch")).toBeInTheDocument();
    expect(screen.queryByText("assistant_message")).not.toBeInTheDocument();
  });
});
