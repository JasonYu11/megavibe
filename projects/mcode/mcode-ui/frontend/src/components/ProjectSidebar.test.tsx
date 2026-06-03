import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectSidebar } from "./ProjectSidebar";

describe("ProjectSidebar", () => {
  afterEach(() => cleanup());

  it("renders projects and sessions", () => {
    render(
      <ProjectSidebar
        projects={[{ id: "p1", name: "Project One", root_path: "/tmp/p1", created_at: 1 }]}
        sessions={[{ id: "s1", path: "/tmp/s1.jsonl", messages: 3, updated_at: 1, preview: "hello session" }]}
        selectedProjectId="p1"
        selectedSessionId="s1"
        selectedProjectRoot="/tmp/p1"
        onSelectProject={vi.fn()}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );
    expect(screen.getByText("Project One")).toBeInTheDocument();
    expect(screen.getByText("/tmp/p1")).toBeInTheDocument();
    expect(screen.getByText("hello session")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加项目" })).toBeInTheDocument();
  });

  it("filters projects and sessions with the search input", () => {
    render(
      <ProjectSidebar
        projects={[
          { id: "p1", name: "Mcode Core", root_path: "/work/mcode", created_at: 1 },
          { id: "p2", name: "Other Project", root_path: "/work/other", created_at: 1 },
        ]}
        sessions={[
          { id: "s1", path: "/tmp/a.jsonl", messages: 3, updated_at: 1, preview: "layout fix" },
          { id: "s2", path: "/tmp/b.jsonl", messages: 2, updated_at: 1, preview: "speech test" },
        ]}
        onSelectProject={vi.fn()}
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("搜索项目和对话"), { target: { value: "layout" } });
    expect(screen.queryByText("Mcode Core")).not.toBeInTheDocument();
    expect(screen.getByText("layout fix")).toBeInTheDocument();
    expect(screen.queryByText("speech test")).not.toBeInTheDocument();
    expect(screen.getByText("无匹配项目")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索项目和对话"), { target: { value: "mcode" } });
    expect(screen.getByText("Mcode Core")).toBeInTheDocument();
    expect(screen.queryByText("Other Project")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索项目和对话"), { target: { value: "" } });
    expect(screen.getByText("Other Project")).toBeInTheDocument();
    expect(screen.getByText("speech test")).toBeInTheDocument();
  });
});
