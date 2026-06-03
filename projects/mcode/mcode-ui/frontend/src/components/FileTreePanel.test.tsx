import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileTreePanel } from "./FileTreePanel";

describe("FileTreePanel", () => {
  it("calls onRead when a file is clicked", () => {
    const onRead = vi.fn();
    render(
      <FileTreePanel
        onRead={onRead}
        tree={{ name: "root", path: "", is_dir: true, children: [{ name: "README.md", path: "README.md", is_dir: false, children: [] }] }}
      />,
    );
    fireEvent.click(screen.getByText("README.md"));
    expect(onRead).toHaveBeenCalledWith("README.md");
  });

  it("opens preview actions with explicit app targets and copies paths", () => {
    const onOpenExternal = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <FileTreePanel
        onRead={vi.fn()}
        onOpenExternal={onOpenExternal}
        selectedPath="README.md"
        fileContent="# Readme"
        tree={{ name: "root", path: "", is_dir: true, children: [{ name: "README.md", path: "README.md", is_dir: false, children: [] }] }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /打开方式/ }));
    fireEvent.click(screen.getByText("Finder 中显示"));
    expect(onOpenExternal).toHaveBeenCalledWith("README.md", "finder");

    fireEvent.click(screen.getByRole("button", { name: /打开方式/ }));
    fireEvent.click(screen.getByText("默认打开"));
    expect(onOpenExternal).toHaveBeenCalledWith("README.md", "system");

    fireEvent.click(screen.getByRole("button", { name: /打开方式/ }));
    fireEvent.click(screen.getByText("使用配置打开"));
    expect(onOpenExternal).toHaveBeenCalledWith("README.md", "");

    fireEvent.click(screen.getByRole("button", { name: /打开方式/ }));
    fireEvent.click(screen.getByText("复制路径"));
    expect(writeText).toHaveBeenCalledWith("README.md");
  });

  it("shows file row context menu actions", () => {
    const onRead = vi.fn();
    const onOpenExternal = vi.fn();
    render(
      <FileTreePanel
        onRead={onRead}
        onOpenExternal={onOpenExternal}
        tree={{ name: "root", path: "", is_dir: true, children: [{ name: "src/App.tsx", path: "src/App.tsx", is_dir: false, children: [] }] }}
      />,
    );

    fireEvent.contextMenu(screen.getByText("src/App.tsx"), { clientX: 40, clientY: 80 });
    fireEvent.click(screen.getByText("预览"));
    expect(onRead).toHaveBeenCalledWith("src/App.tsx");
  });
});
