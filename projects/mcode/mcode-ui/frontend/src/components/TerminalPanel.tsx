import { Plus, Play, RefreshCw, Send, SquareTerminal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { JobInfo, RuntimeInfo, TerminalSessionInfo } from "../types";

export function TerminalPanel({
  projectId,
  jobs,
  runtime,
  onRuntimeChange,
}: {
  projectId?: string;
  jobs: JobInfo[];
  runtime?: RuntimeInfo | null;
  onRuntimeChange?: (patch: { python?: string; shell?: string }) => void;
}) {
  const [shellDraft, setShellDraft] = useState(runtime?.shell || "");
  const [terminals, setTerminals] = useState<TerminalSessionInfo[]>([]);
  const [activeId, setActiveId] = useState("");
  const [output, setOutput] = useState("");
  const [cursor, setCursor] = useState(0);
  const [command, setCommand] = useState("");
  const [error, setError] = useState("");
  const outputRef = useRef<HTMLPreElement | null>(null);
  const cursorRef = useRef(0);

  useEffect(() => {
    setShellDraft(runtime?.shell || "");
  }, [runtime?.shell]);

  useEffect(() => {
    setTerminals([]);
    setActiveId("");
    setOutput("");
    setCursor(0);
    if (!projectId) return;
    void refreshTerminals(projectId);
  }, [projectId]);

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await api.readTerminal(activeId, cursorRef.current);
        if (cancelled) return;
        if (data.chunk) setOutput((prev) => prev + data.chunk);
        cursorRef.current = data.cursor;
        setCursor(data.cursor);
        setTerminals((prev) => prev.map((item) => (item.id === data.id ? { ...item, ...data } : item)));
      } catch (exc) {
        if (!cancelled) setError(String(exc));
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 600);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeId]);

  useEffect(() => {
    const node = outputRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [output]);

  async function refreshTerminals(id = projectId) {
    if (!id) return;
    const rows = await api.terminals(id);
    setTerminals(rows);
    if (!activeId && rows[0]) selectTerminal(rows[0]);
  }

  async function createTerminal(kind: "python" | "shell" = "python") {
    if (!projectId) return;
    setError("");
    const term = await api.createTerminal(projectId, {
      kind,
      shell: runtime?.shell || "",
      python: runtime?.python || "",
    });
    setTerminals((prev) => [term, ...prev]);
    selectTerminal(term);
  }

  function selectTerminal(term: TerminalSessionInfo) {
    setActiveId(term.id);
    setOutput(term.output || "");
    cursorRef.current = term.cursor || 0;
    setCursor(term.cursor || 0);
  }

  async function closeTerminal(id: string) {
    await api.closeTerminal(id);
    setTerminals((prev) => prev.filter((item) => item.id !== id));
    if (id === activeId) {
      setActiveId("");
      setOutput("");
      setCursor(0);
    }
  }

  async function submitCommand(event: FormEvent) {
    event.preventDefault();
    if (!activeId || !command.trim()) return;
    const text = command.endsWith("\n") ? command : `${command}\n`;
    setCommand("");
    await api.writeTerminal(activeId, text);
  }

  const active = terminals.find((item) => item.id === activeId);

  return (
    <div className="panelBody">
      <section className="terminalPanel">
        <div className="terminalPanel__top">
          <div className="terminalTabs">
            {terminals.map((term) => (
              <button
                className={`terminalTab ${term.id === activeId ? "is-active" : ""}`}
                key={term.id}
                onClick={() => selectTerminal(term)}
                title={term.cwd}
              >
                <SquareTerminal size={13} />
                {term.kind === "python" ? "Python" : lastPathName(term.cwd) || "Shell"}
                <span>{term.running ? "●" : "×"}</span>
              </button>
            ))}
          </div>
          <button className="iconButton" onClick={() => void createTerminal("python")} disabled={!projectId} title="新建 Python 终端">
            <Plus size={15} />
          </button>
        </div>
        {active ? (
          <>
            <pre className="terminalScreen" ref={outputRef}>{output || "启动终端中..."}</pre>
            <form className="terminalInput" onSubmit={(event) => void submitCommand(event)}>
              <input
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder={active.running ? "输入命令后回车" : "终端已退出"}
                disabled={!active.running}
                aria-label="Terminal command"
              />
              <button className="iconButton" disabled={!active.running || !command.trim()} title="发送命令">
                <Send size={15} />
              </button>
              <button className="iconButton" type="button" onClick={() => void closeTerminal(active.id)} title="关闭终端">
                <X size={15} />
              </button>
            </form>
          </>
        ) : (
          <div className="terminalEmpty">
            <SquareTerminal size={20} />
            <span>新建一个 Python 终端，或打开 shell 终端运行项目命令。</span>
            <button className="primaryButton" onClick={() => void createTerminal("python")} disabled={!projectId}>
              新建 Python
            </button>
            <button className="secondaryButton" onClick={() => void createTerminal("shell")} disabled={!projectId}>
              新建 Shell
            </button>
          </div>
        )}
        {error && <button className="terminalError" onClick={() => setError("")}>{error}</button>}
      </section>
      <section className="runtimePanel">
        <div className="runtimePanel__title">
          <SquareTerminal size={15} />
          <strong>运行环境</strong>
        </div>
        <label className="runtimeField">
          <span>Python</span>
          <select
            value={runtime?.python || ""}
            onChange={(event) => onRuntimeChange?.({ python: event.target.value })}
            disabled={!runtime}
          >
            {!runtime && <option value="">加载中</option>}
            {runtime?.candidates.map((candidate) => (
              <option value={candidate.path} key={candidate.path}>
                {candidate.label} · {candidate.source}
              </option>
            ))}
          </select>
        </label>
        <div className="runtimePath" title={runtime?.python || ""}>
          {runtime?.python || "未发现 Python"}
        </div>
        <label className="runtimeField">
          <span>Shell</span>
          <input
            value={shellDraft}
            onChange={(event) => setShellDraft(event.target.value)}
            onBlur={() => {
              if (runtime && shellDraft.trim() !== runtime.shell) onRuntimeChange?.({ shell: shellDraft });
            }}
            disabled={!runtime}
          />
        </label>
        <div className="runtimeHint">
          <Play size={13} />
          默认终端使用 Python 交互模式；Shell 终端可从上方手动创建。
        </div>
      </section>
      <div className="panelDivider">
        <RefreshCw size={13} />
        后台任务
      </div>
      {jobs.length === 0 && <div className="emptyNote">暂无后台终端任务</div>}
      {jobs.map((job) => (
        <div className="jobCard" key={job.job_id}>
          <div className="jobCard__head">
            <strong>
              {job.job_id}
              {job.kind ? <span className="jobKind">{job.kind}</span> : null}
            </strong>
            <span>{new Date(job.updated_at * 1000).toLocaleTimeString()}</span>
          </div>
          <pre>{job.tail || "(no output)"}</pre>
        </div>
      ))}
    </div>
  );
}

function lastPathName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}
