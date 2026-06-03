import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectPickerDialog } from "./ProjectPickerDialog";

afterEach(() => cleanup());

describe("ProjectPickerDialog", () => {
  it("creates from picked folder", () => {
    const onCreate = vi.fn();
    render(
      <ProjectPickerDialog
        open
        busy={false}
        picked={{ cancelled: false, root_path: "/tmp/empty-project", name: "empty-project" }}
        onPickFolder={vi.fn()}
        onCreate={onCreate}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("添加"));
    expect(onCreate).toHaveBeenCalledWith("empty-project", "/tmp/empty-project");
  });

  it("keeps manual path fallback", () => {
    const onCreate = vi.fn();
    render(
      <ProjectPickerDialog open busy={false} onPickFolder={vi.fn()} onCreate={onCreate} onClose={vi.fn()} />,
    );
    fireEvent.change(screen.getByPlaceholderText("/Users/macbot/project"), { target: { value: "/tmp/manual" } });
    fireEvent.click(screen.getByText("添加"));
    expect(onCreate).toHaveBeenCalledWith("manual", "/tmp/manual");
  });
});
