import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FinalAnswerRenderer, normalizeFinalAnswer } from "./FinalAnswerRenderer";

describe("FinalAnswerRenderer", () => {
  it("removes report-style headings and decorative emoji", () => {
    const normalized = normalizeFinalAnswer("### 📋 完整工作回顾\n\n**执行总结：**\n\n**1. 创建仿真脚本**\n验证：运行通过");
    expect(normalized.lines).toEqual(["创建仿真脚本", "验证：运行通过"]);
  });

  it("highlights file paths", () => {
    render(<FinalAnswerRenderer text="已生成 /tmp/demo/lfm_matched_filter.py 和 result.png" />);
    expect(screen.getByText("/tmp/demo/lfm_matched_filter.py").tagName.toLowerCase()).toBe("code");
    expect(screen.getByText("result.png").tagName.toLowerCase()).toBe("code");
  });

  it("opens file paths when an opener is provided", () => {
    const openFile = vi.fn();
    render(<FinalAnswerRenderer text="改动文件：FileTreePanel.tsx 和 mini_agent_lab/control.py" onOpenFile={openFile} />);
    fireEvent.click(screen.getByText("FileTreePanel.tsx"));
    fireEvent.click(screen.getByText("mini_agent_lab/control.py"));
    expect(openFile).toHaveBeenNthCalledWith(1, "FileTreePanel.tsx");
    expect(openFile).toHaveBeenNthCalledWith(2, "mini_agent_lab/control.py");
  });

  it("collapses long answers by default", () => {
    const text = Array.from({ length: 14 }, (_, index) => `line ${index + 1}`).join("\n");
    render(<FinalAnswerRenderer text={text} />);
    expect(screen.queryByText("line 14")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("展开完整回答"));
    expect(screen.getByText("line 14")).toBeInTheDocument();
  });
});
