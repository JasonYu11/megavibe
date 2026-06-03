import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceDock } from "./WorkspaceDock";

vi.mock("../api/client", () => ({
  api: {
    settings: vi.fn(async () => ({
      provider: {
        base_url: "https://api.deepseek.com",
        model: "deepseek-v4-flash",
        thinking_mode: false,
        temperature: 0.2,
        timeout_seconds: 30,
        max_retries: 4,
        proxy_url: "",
        trust_env: false,
      },
      agent: { max_steps: 300 },
      context: {
        context_window_tokens: 200000,
        compact_ratio: 0.75,
        chars_per_token: 3,
        recent_keep: 12,
        auto_compact: true,
        summary_mode: "llm",
        target_summary_ratio: 0.1,
        min_summary_tokens: 10000,
        max_summary_tokens: 20000,
      },
      paths: {},
      runtime: { shell: "/bin/zsh", python: "", python_preference: "conda" },
      ui: { language: "zh", theme: "system", file_open_app: "cursor", show_thought_summary: true },
      api_key_configured: true,
    })),
    updateSettings: vi.fn(async (_projectId, settings) => settings),
    saveApiKey: vi.fn(async (_projectId, _value) => ({
      provider: {
        base_url: "https://api.deepseek.com",
        model: "deepseek-v4-flash",
        thinking_mode: false,
        temperature: 0.2,
        timeout_seconds: 30,
        max_retries: 4,
        proxy_url: "",
        trust_env: false,
      },
      agent: { max_steps: 300 },
      context: {
        context_window_tokens: 200000,
        compact_ratio: 0.75,
        chars_per_token: 3,
        recent_keep: 12,
        auto_compact: true,
        summary_mode: "llm",
        target_summary_ratio: 0.1,
        min_summary_tokens: 10000,
        max_summary_tokens: 20000,
      },
      paths: {},
      runtime: { shell: "/bin/zsh", python: "", python_preference: "conda" },
      ui: { language: "zh", theme: "system", file_open_app: "cursor", show_thought_summary: true },
      api_key_configured: true,
    })),
    clearApiKey: vi.fn(async () => ({
      provider: {
        base_url: "https://api.deepseek.com",
        model: "deepseek-v4-flash",
        thinking_mode: false,
        temperature: 0.2,
        timeout_seconds: 30,
        max_retries: 4,
        proxy_url: "",
        trust_env: false,
      },
      agent: { max_steps: 300 },
      context: {
        context_window_tokens: 200000,
        compact_ratio: 0.75,
        chars_per_token: 3,
        recent_keep: 12,
        auto_compact: true,
        summary_mode: "llm",
        target_summary_ratio: 0.1,
        min_summary_tokens: 10000,
        max_summary_tokens: 20000,
      },
      paths: {},
      runtime: { shell: "/bin/zsh", python: "", python_preference: "conda" },
      ui: { language: "zh", theme: "system", file_open_app: "cursor", show_thought_summary: true },
      api_key_configured: false,
    })),
    apiTest: vi.fn(),
    terminals: vi.fn(async () => []),
    createTerminal: vi.fn(),
    readTerminal: vi.fn(),
    closeTerminal: vi.fn(),
    createSession: vi.fn(),
    send: vi.fn(),
    session: vi.fn(),
  },
}));

afterEach(() => cleanup());

const baseProps = {
  tree: {
    name: "root",
    path: "",
    is_dir: true,
    children: [{ name: "demo.py", path: "demo.py", is_dir: false, children: [] }],
  },
  selectedPath: "",
  fileContent: "",
  events: [],
  jobs: [],
  subagents: [],
  runtime: {
    shell: "/bin/zsh",
    python: "/usr/bin/python3",
    python_source: "system",
    candidates: [{ path: "/usr/bin/python3", label: "python3", source: "system", selected: true }],
  },
  projectId: "mcode",
  onReadFile: vi.fn(),
  onRuntimeChange: vi.fn(),
};

describe("WorkspaceDock", () => {
  it("renders pane header actions", () => {
    const onHide = vi.fn();
    render(<WorkspaceDock {...baseProps} onHide={onHide} />);
    expect(screen.getByRole("button", { name: "添加工具窗格" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "隐藏工具区" }));
    expect(onHide).toHaveBeenCalledOnce();
  });

  it("creates tool panes from the dock plus menu", () => {
    render(<WorkspaceDock {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: "添加工具窗格" }));
    fireEvent.click(screen.getByText("添加终端窗格"));
    expect(screen.getByRole("tab", { name: /终端/ })).toBeInTheDocument();
    expect(screen.getByText("运行环境")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加工具窗格" }));
    fireEvent.click(screen.getByText("添加浏览器窗格"));
    expect(screen.getByRole("tab", { name: /浏览器/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Browser URL")).toBeInTheDocument();
  });

  it("opens file and terminal panels", () => {
    render(<WorkspaceDock {...baseProps} />);
    expect(screen.getByTestId("file-tree")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "`", ctrlKey: true });
    expect(screen.getByText("运行环境")).toBeInTheDocument();
  });

  it("loads settings, hides the API key, and saves changes", async () => {
    const { api } = await import("../api/client");
    render(<WorkspaceDock {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: "添加工具窗格" }));
    fireEvent.click(screen.getByText("添加设置窗格"));
    await screen.findByText("项目设置");
    expect(screen.getByText("API Key：已配置")).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/sk-/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-new" } });
    fireEvent.click(screen.getByText("保存 Key"));
    await waitFor(() => expect(api.saveApiKey).toHaveBeenCalledWith("mcode", "sk-new"));
    fireEvent.change(screen.getByLabelText("Timeout"), { target: { value: "45" } });
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalled());
  });

  it("supports keyboard shortcuts", () => {
    render(<WorkspaceDock {...baseProps} />);
    fireEvent.keyDown(window, { key: "p", metaKey: true });
    expect(screen.getByTestId("file-tree")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "`", ctrlKey: true });
    expect(screen.getByText("运行环境")).toBeInTheDocument();
  });
});
