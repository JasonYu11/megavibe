import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ProjectSettings } from "../types";
import { SettingsPanel } from "./SettingsPanel";

vi.mock("../api/client", () => ({
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    saveApiKey: vi.fn(),
    clearApiKey: vi.fn(),
    apiTest: vi.fn(),
  },
}));

describe("SettingsPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders section navigation and switches settings content", async () => {
    vi.mocked(api.settings).mockResolvedValue(settingsFixture());
    render(<SettingsPanel projectId="p1" runtime={runtimeFixture()} onRuntimeChange={vi.fn()} />);

    await screen.findByText("模型与 API");
    expect(screen.getByText("Agent 与上下文")).toBeInTheDocument();
    expect(screen.getByText("运行环境")).toBeInTheDocument();
    expect(screen.getByText("文件打开")).toBeInTheDocument();
    expect(screen.getByText("诊断")).toBeInTheDocument();

    fireEvent.click(screen.getByText("运行环境"));
    expect(screen.getByText("Python")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Agent 与上下文"));
    expect(screen.getByLabelText("思考摘要")).toBeInTheDocument();

    fireEvent.click(screen.getByText("文件打开"));
    expect(screen.getByLabelText("默认 IDE / App")).toBeInTheDocument();
  });

  it("keeps save, api key, clear key, and runtime behaviors wired", async () => {
    const onRuntimeChange = vi.fn();
    vi.mocked(api.settings).mockResolvedValue(settingsFixture());
    vi.mocked(api.updateSettings).mockResolvedValue({
      ...settingsFixture(),
      provider: { ...settingsFixture().provider, base_url: "https://next.example" },
    });
    vi.mocked(api.saveApiKey).mockResolvedValue(settingsFixture({ api_key_configured: true }));
    vi.mocked(api.clearApiKey).mockResolvedValue(settingsFixture({ api_key_configured: false }));
    render(<SettingsPanel projectId="p1" runtime={runtimeFixture()} onRuntimeChange={onRuntimeChange} />);

    await screen.findByText("模型与 API");
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://next.example" } });
    fireEvent.click(screen.getByText("Agent 与上下文"));
    fireEvent.click(screen.getByLabelText("思考摘要"));
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalled());
    const updateCalls = vi.mocked(api.updateSettings).mock.calls;
    expect(updateCalls[updateCalls.length - 1]?.[1]).toMatchObject({
      provider: { base_url: "https://next.example" },
      ui: { show_thought_summary: false },
    });

    fireEvent.click(screen.getByText("模型与 API"));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByText("保存 Key"));
    await waitFor(() => expect(api.saveApiKey).toHaveBeenCalledWith("p1", "sk-test"));

    fireEvent.click(screen.getByText("清除"));
    await waitFor(() => expect(api.clearApiKey).toHaveBeenCalledWith("p1"));

    fireEvent.click(screen.getByText("运行环境"));
    fireEvent.change(screen.getByLabelText("Shell"), { target: { value: "/bin/bash" } });
    fireEvent.blur(screen.getByLabelText("Shell"));
    expect(onRuntimeChange).toHaveBeenCalledWith({ shell: "/bin/bash" });
  });
});

function settingsFixture(patch: Partial<ProjectSettings> = {}): ProjectSettings {
  const base: ProjectSettings = {
    provider: {
      base_url: "https://api.deepseek.com",
      model: "deepseek-chat",
      thinking_mode: false,
      temperature: 0.2,
      timeout_seconds: 60,
      max_retries: 2,
      proxy_url: "",
      trust_env: true,
    },
    agent: { max_steps: 12 },
    context: {
      context_window_tokens: 120000,
      compact_ratio: 0.35,
      chars_per_token: 4,
      recent_keep: 10,
      auto_compact: true,
      summary_mode: "compact",
      target_summary_ratio: 0.35,
      min_summary_tokens: 1000,
      max_summary_tokens: 8000,
    },
    paths: {},
    runtime: { shell: "/bin/zsh", python: "/usr/bin/python3", python_preference: "auto" },
    ui: { language: "zh-CN", theme: "system", file_open_app: "cursor", show_thought_summary: true },
    auto_review: {
      enabled: true,
      model: "deepseek-chat",
      temperature: 0.0,
      skip_tools: [],
      always_escalate: [],
      strictness: {},
    },
    api_key_configured: false,
  };
  return {
    ...base,
    ...patch,
    provider: { ...base.provider, ...(patch.provider || {}) },
    ui: { ...base.ui, ...(patch.ui || {}) },
  };
}

function runtimeFixture() {
  return {
    shell: "/bin/zsh",
    python: "/usr/bin/python3",
    python_source: "system",
    candidates: [{ path: "/usr/bin/python3", label: "Python", source: "system", selected: true }],
  };
}
