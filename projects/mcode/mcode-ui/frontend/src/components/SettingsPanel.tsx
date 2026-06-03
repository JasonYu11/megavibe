import { Activity, Brain, FileEdit, KeyRound, Palette, Save, Settings, Shield, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { MODEL_PRESETS, presetById, presetIdFor } from "../modelPresets";
import type { ApiTestResult, ProjectSettings, RuntimeInfo } from "../types";

type SettingsSectionId = "provider" | "agent" | "safety" | "runtime" | "appearance" | "files" | "diagnostics";

const SETTINGS_SECTIONS: Array<{ id: SettingsSectionId; label: string; description: string }> = [
  { id: "provider", label: "模型与 API", description: "模型、Base URL、Key" },
  { id: "agent", label: "Agent 与上下文", description: "步数、压缩、窗口" },
  { id: "safety", label: "安全审查", description: "自审 Agent 配置" },
  { id: "runtime", label: "运行环境", description: "Python 与 shell" },
  { id: "appearance", label: "外观", description: "主题与配色" },
  { id: "files", label: "文件打开", description: "默认 IDE / App" },
  { id: "diagnostics", label: "诊断", description: "API 稳定性测试" },
];

export function SettingsPanel({
  projectId,
  runtime,
  onRuntimeChange,
}: {
  projectId?: string;
  runtime?: RuntimeInfo | null;
  onRuntimeChange?: (patch: { python?: string; shell?: string }) => void;
}) {
  const [settings, setSettings] = useState<ProjectSettings | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [shellDraft, setShellDraft] = useState(runtime?.shell || "");
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<ApiTestResult | null>(null);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("provider");

  useEffect(() => {
    setShellDraft(runtime?.shell || "");
  }, [runtime?.shell]);

  useEffect(() => {
    setSettings(null);
    setApiKeyDraft("");
    setTestResult(null);
    if (!projectId) return;
    void api.settings(projectId).then(setSettings).catch((exc) => setError(String(exc)));
  }, [projectId]);

  async function save() {
    if (!projectId || !settings) return;
    setBusy(true);
    setError("");
    try {
      setSettings(await api.updateSettings(projectId, settings));
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      setTestResult(await api.apiTest(projectId, 3));
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function saveApiKey() {
    if (!projectId || !apiKeyDraft.trim()) return;
    setBusy(true);
    setError("");
    try {
      setSettings(await api.saveApiKey(projectId, apiKeyDraft));
      setApiKeyDraft("");
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function clearApiKey() {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      setSettings(await api.clearApiKey(projectId));
      setApiKeyDraft("");
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }

  if (!settings) {
    return (
      <div className="panelBody">
        <div className="dockEmpty">
          <Settings size={24} />
          <strong>设置</strong>
          <span>{projectId ? "加载设置中..." : "先选择项目"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="panelBody settingsPanel">
      <div className="settingsPanel__head">
        <div>
          <Settings size={17} />
          <strong>项目设置</strong>
        </div>
        <button className="primaryButton" onClick={() => void save()} disabled={busy}>
          <Save size={14} />
          保存
        </button>
      </div>

      <div className="settingsPanel__layout">
        <nav className="settingsNav" aria-label="设置分区">
          {SETTINGS_SECTIONS.map((section) => (
            <button
              key={section.id}
              className={activeSection === section.id ? "is-active" : ""}
              onClick={() => setActiveSection(section.id)}
              type="button"
            >
              <span>{section.label}</span>
              <small>{section.description}</small>
            </button>
          ))}
        </nav>
        <div className="settingsPanel__content">
      {activeSection === "provider" && <section className="settingsSection">
        <h3>模型 / API</h3>
        <Field label="Base URL">
          <input value={settings.provider.base_url} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, base_url: event.target.value } })} />
        </Field>
        <Field label="Model">
          <select
            value={presetIdFor(settings.provider.model, settings.provider.thinking_mode)}
            onChange={(event) => {
              const preset = presetById(event.target.value);
              setSettings({
                ...settings,
                provider: { ...settings.provider, model: preset.model, thinking_mode: preset.thinkingMode },
              });
            }}
          >
            {MODEL_PRESETS.map((preset) => (
              <option value={preset.id} key={preset.id}>
                {preset.label}
                {preset.thinkingMode ? " · thinking" : ""}
              </option>
            ))}
          </select>
        </Field>
        <div className="apiKeyStatus">
          <Brain size={14} />
          思考模式：{settings.provider.thinking_mode ? "开启" : "关闭"}
        </div>
        <div className="settingsGrid">
          <Field label="Temperature">
            <input type="number" step="0.1" value={settings.provider.temperature} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, temperature: Number(event.target.value) } })} />
          </Field>
          <Field label="Timeout">
            <input type="number" value={settings.provider.timeout_seconds} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, timeout_seconds: Number(event.target.value) } })} />
          </Field>
          <Field label="Retries">
            <input type="number" value={settings.provider.max_retries} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, max_retries: Number(event.target.value) } })} />
          </Field>
          <Field label="Trust env">
            <input type="checkbox" checked={settings.provider.trust_env} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, trust_env: event.target.checked } })} />
          </Field>
        </div>
        <Field label="Proxy URL">
          <input value={settings.provider.proxy_url} onChange={(event) => setSettings({ ...settings, provider: { ...settings.provider, proxy_url: event.target.value } })} />
        </Field>
        <div className="apiKeyStatus">
          <KeyRound size={14} />
          API Key：{settings.api_key_configured ? "已配置" : "未配置"}
        </div>
        <div className="apiKeyEditor">
          <Field label="API Key">
            <input
              type="password"
              autoComplete="off"
              value={apiKeyDraft}
              onChange={(event) => setApiKeyDraft(event.target.value)}
              placeholder={settings.api_key_configured ? "输入新 key 以替换当前配置" : "输入 DeepSeek API key"}
            />
          </Field>
          <div className="apiKeyActions">
            <button className="secondaryButton" onClick={() => void saveApiKey()} disabled={busy || !apiKeyDraft.trim()}>
              <KeyRound size={14} />
              保存 Key
            </button>
            <button className="ghostButton" onClick={() => void clearApiKey()} disabled={busy || !settings.api_key_configured}>
              <Trash2 size={14} />
              清除
            </button>
          </div>
        </div>
      </section>}

      {activeSection === "agent" && <section className="settingsSection">
        <h3>Agent / Context</h3>
        <div className="settingsGrid">
          <Field label="Max steps">
            <input type="number" value={settings.agent.max_steps} onChange={(event) => setSettings({ ...settings, agent: { max_steps: Number(event.target.value) } })} />
          </Field>
          <Field label="Context window">
            <input type="number" value={settings.context.context_window_tokens} onChange={(event) => setSettings({ ...settings, context: { ...settings.context, context_window_tokens: Number(event.target.value) } })} />
          </Field>
          <Field label="Compact ratio">
            <input type="number" step="0.05" value={settings.context.compact_ratio} onChange={(event) => setSettings({ ...settings, context: { ...settings.context, compact_ratio: Number(event.target.value) } })} />
          </Field>
          <Field label="Recent keep">
            <input type="number" value={settings.context.recent_keep} onChange={(event) => setSettings({ ...settings, context: { ...settings.context, recent_keep: Number(event.target.value) } })} />
          </Field>
          <Field label="Auto compact">
            <input type="checkbox" checked={settings.context.auto_compact} onChange={(event) => setSettings({ ...settings, context: { ...settings.context, auto_compact: event.target.checked } })} />
          </Field>
          <Field label="思考摘要">
            <input
              type="checkbox"
              checked={settings.ui.show_thought_summary ?? true}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  ui: { ...settings.ui, show_thought_summary: event.target.checked },
                })
              }
            />
          </Field>
          <Field label="Summary max">
            <input type="number" value={settings.context.max_summary_tokens} onChange={(event) => setSettings({ ...settings, context: { ...settings.context, max_summary_tokens: Number(event.target.value) } })} />
          </Field>
        </div>
      </section>}

      {activeSection === "safety" && <section className="settingsSection">
        <h3>安全审查 (AutoReviewAgent)</h3>
        <p className="fieldHint">
          当静态规则判定为 "需要确认" 的工具调用，由 LLM 审查 Agent 根据用户意图自动决定放行或拒绝。
          配置文件：<code>mcode-policy.json</code> → auto_review
        </p>
        <div className="settingsGrid">
          <Field label="启用自动审查">
            <input
              type="checkbox"
              checked={settings.auto_review?.enabled ?? true}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  auto_review: { ...(settings.auto_review || {}), enabled: event.target.checked },
                })
              }
            />
          </Field>
          <Field label="审查模型">
            <select
              value={settings.auto_review?.model || "deepseek-chat"}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  auto_review: { ...(settings.auto_review || {}), model: event.target.value },
                })
              }
            >
              <option value="deepseek-chat">DeepSeek-Chat (轻量)</option>
              <option value="deepseek-reasoner">DeepSeek-Reasoner (深度)</option>
            </select>
          </Field>
          <Field label="Temperature">
            <input
              type="number"
              step="0.1"
              min="0"
              max="1"
              value={settings.auto_review?.temperature ?? 0.0}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  auto_review: { ...(settings.auto_review || {}), temperature: Number(event.target.value) },
                })
              }
            />
          </Field>
        </div>
        <div className="apiKeyStatus" style={{ marginTop: 12 }}>
          <Shield size={14} />
          {settings.auto_review?.enabled !== false ? "自动审查已启用 — ask 决定先由 LLM 审查" : "自动审查已关闭 — ask 决定直接弹窗问用户"}
        </div>
        <button
          className="secondaryButton"
          style={{ marginTop: 12 }}
          onClick={async () => {
            if (!projectId) return;
            try {
              const policy = await api.policy(projectId);
              const blob = new Blob([JSON.stringify(policy, null, 2)], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              window.open(url, "_blank");
            } catch (e) {
              console.error("Failed to load policy", e);
            }
          }}
        >
          <FileEdit size={14} />
          打开完整策略配置文件
        </button>
      </section>}

      {activeSection === "runtime" && <section className="settingsSection">
        <h3>Runtime</h3>
        <Field label="Python">
          <select value={runtime?.python || ""} onChange={(event) => onRuntimeChange?.({ python: event.target.value })} disabled={!runtime}>
            {runtime?.candidates.map((candidate) => (
              <option value={candidate.path} key={candidate.path}>
                {candidate.label} · {candidate.source}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Shell">
          <input
            value={shellDraft}
            onChange={(event) => setShellDraft(event.target.value)}
            onBlur={() => {
              if (runtime && shellDraft.trim() !== runtime.shell) onRuntimeChange?.({ shell: shellDraft });
            }}
          />
        </Field>
      </section>}

      {activeSection === "appearance" && <section className="settingsSection">
        <h3>外观</h3>
        <Field label="主题">
          <select
            value={document.documentElement.classList.contains("theme-dark") ? "dark" : "light"}
            onChange={(event) => {
              const value = event.target.value;
              document.documentElement.classList.toggle("theme-dark", value === "dark");
              try { localStorage.setItem("mcode-theme", value); } catch { /* ignore */ }
            }}
          >
            <option value="light">Codex Light</option>
            <option value="dark">Codex Dark</option>
          </select>
        </Field>
        <p className="fieldHint" style={{ marginTop: 8 }}>
          强调色 #339CFF — 浅色背景 #FFFFFF / 深色背景 #181818
        </p>
      </section>}

      {activeSection === "files" && <section className="settingsSection">
        <h3>文件打开方式</h3>
        <Field label="默认 IDE / App">
          <select
            value={knownOpenApp(settings.ui.file_open_app) ? settings.ui.file_open_app : "custom"}
            onChange={(event) => {
              const value = event.target.value;
              setSettings({
                ...settings,
                ui: { ...settings.ui, file_open_app: value === "custom" ? settings.ui.file_open_app || "Cursor" : value },
              });
            }}
          >
            <option value="cursor">Cursor</option>
            <option value="vscode">Visual Studio Code</option>
            <option value="finder">Finder 中显示</option>
            <option value="system">系统默认</option>
            <option value="custom">其它 App 名称</option>
          </select>
        </Field>
        {!knownOpenApp(settings.ui.file_open_app) && (
          <Field label="App 名称">
            <input
              value={settings.ui.file_open_app}
              onChange={(event) => setSettings({ ...settings, ui: { ...settings.ui, file_open_app: event.target.value } })}
              placeholder="例如 Sublime Text"
            />
          </Field>
        )}
      </section>}

      {activeSection === "diagnostics" && <section className="settingsSection">
        <h3>Diagnostics</h3>
        <button className="secondaryButton" onClick={() => void runTest()} disabled={busy}>
          <Activity size={14} />
          API 稳定性测试
        </button>
        {testResult && (
          <div className="apiTestResult">
            <strong>
              {testResult.summary.ok}/{testResult.summary.total} 成功
            </strong>
            <span>median {testResult.summary.median_seconds ?? "-"}s · p95 {testResult.summary.p95_seconds ?? "-"}s · max {testResult.summary.max_seconds ?? "-"}s</span>
            {Object.keys(testResult.summary.errors).length > 0 && <pre>{JSON.stringify(testResult.summary.errors, null, 2)}</pre>}
          </div>
        )}
      </section>}
        </div>
      </div>
      {error && <button className="terminalError" onClick={() => setError("")}>{error}</button>}
    </div>
  );
}

function knownOpenApp(value: string): boolean {
  return ["cursor", "vscode", "finder", "system"].includes((value || "").toLowerCase());
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="settingsField">
      <span>{label}</span>
      {children}
    </label>
  );
}
