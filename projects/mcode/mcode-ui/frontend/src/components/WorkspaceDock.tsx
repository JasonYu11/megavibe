import { Files, Globe, ListTree, MessageCirclePlus, PanelRightClose, Plus, Settings, SquareTerminal, Workflow, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { FileNode, JobInfo, RunEvent, RuntimeInfo, SubagentInfo } from "../types";
import { BrowserPanel } from "./BrowserPanel";
import { EventTimeline } from "./EventTimeline";
import { FileTreePanel } from "./FileTreePanel";
import { SettingsPanel } from "./SettingsPanel";
import { SideChatPanel } from "./SideChatPanel";
import { SubagentPanel } from "./SubagentPanel";
import { TerminalPanel } from "./TerminalPanel";

export type DockView = "files" | "side_chat" | "browser" | "terminal" | "settings" | "events" | "subagents";

interface DockPane {
  id: string;
  type: DockView;
  title: string;
}

const PANE_TYPES: DockView[] = ["files", "terminal", "browser", "events", "subagents", "settings", "side_chat"];

export function WorkspaceDock({
  tree,
  selectedPath,
  fileContent,
  events,
  jobs,
  subagents,
  runtime,
  projectId,
  view,
  onViewChange,
  onHide,
  onReadFile,
  onOpenFileExternal,
  onRuntimeChange,
}: {
  tree?: FileNode | null;
  selectedPath?: string;
  fileContent?: string;
  events: RunEvent[];
  jobs: JobInfo[];
  subagents: SubagentInfo[];
  runtime?: RuntimeInfo | null;
  projectId?: string;
  view?: DockView;
  onViewChange?: (view: DockView) => void;
  onHide?: () => void;
  onReadFile: (path: string) => void;
  onOpenFileExternal?: (path: string, app?: string) => void;
  onRuntimeChange?: (patch: { python?: string; shell?: string }) => void;
}) {
  const paneCounter = useRef(1);
  const [panes, setPanes] = useState<DockPane[]>([{ id: "files-1", type: "files", title: titleFor("files") }]);
  const [activePaneId, setActivePaneId] = useState("files-1");
  const [addOpen, setAddOpen] = useState(false);
  const activePane = panes.find((pane) => pane.id === activePaneId) || panes[0];
  const activeView = activePane?.type || "files";

  const makePane = (type: DockView, existing: DockPane[]): DockPane => {
    const sameTypeCount = existing.filter((pane) => pane.type === type).length;
    paneCounter.current += 1;
    return {
      id: `${type}-${paneCounter.current}`,
      type,
      title: sameTypeCount > 0 ? `${titleFor(type)} ${sameTypeCount + 1}` : titleFor(type),
    };
  };

  const activatePane = (pane: DockPane) => {
    setActivePaneId(pane.id);
    onViewChange?.(pane.type);
  };

  const activateOrAddPane = (type: DockView) => {
    setPanes((current) => {
      const existing = current.find((pane) => pane.type === type);
      if (existing) {
        setActivePaneId(existing.id);
        onViewChange?.(existing.type);
        return current;
      }
      const nextPane = makePane(type, current);
      setActivePaneId(nextPane.id);
      onViewChange?.(nextPane.type);
      return [...current, nextPane];
    });
    setAddOpen(false);
  };

  const addPane = (type: DockView) => {
    setPanes((current) => {
      const nextPane = makePane(type, current);
      setActivePaneId(nextPane.id);
      onViewChange?.(nextPane.type);
      return [...current, nextPane];
    });
    setAddOpen(false);
  };

  const closePane = (id: string) => {
    setPanes((current) => {
      if (current.length <= 1) return current;
      const closingIndex = current.findIndex((pane) => pane.id === id);
      const next = current.filter((pane) => pane.id !== id);
      if (id === activePaneId) {
        const nextActive = next[Math.max(0, closingIndex - 1)] || next[0];
        setActivePaneId(nextActive.id);
        onViewChange?.(nextActive.type);
      }
      return next;
    });
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "p") {
        event.preventDefault();
        activateOrAddPane("files");
      }
      if (event.ctrlKey && event.key === "`") {
        event.preventDefault();
        activateOrAddPane("terminal");
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "t") {
        event.preventDefault();
        activateOrAddPane("browser");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activePaneId]);

  useEffect(() => {
    if (selectedPath) activateOrAddPane("files");
  }, [selectedPath]);

  useEffect(() => {
    if (!view) return;
    activateOrAddPane(view);
  }, [view]);

  return (
    <aside className="workspaceDock" data-testid="workspace-dock">
      <div className="dockHeader">
        <div className="dockHeader__title">
          <strong>{activePane?.title || titleFor(activeView)}</strong>
          <span>{projectId ? "Inspector" : "先选择项目"}</span>
          <div className="dockHeader__actions">
            <button className="dockIconButton" onClick={() => setAddOpen((value) => !value)} aria-label="添加工具窗格" title="添加工具窗格">
              <Plus size={14} />
            </button>
            <button className="dockIconButton" onClick={onHide} aria-label="隐藏工具区" title="隐藏工具区">
              <PanelRightClose size={14} />
            </button>
            {addOpen && (
              <div className="dockAddMenu">
                {PANE_TYPES.map((type) => (
                  <button key={type} onClick={() => addPane(type)} type="button">
                    {iconFor(type)}
                    <span>添加{titleFor(type)}窗格</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="dockHeader__tools" role="tablist" aria-label="Workspace panes">
          {panes.map((pane) => (
            <MiniTab
              key={pane.id}
              active={pane.id === activePaneId}
              onClick={() => activatePane(pane)}
              onClose={panes.length > 1 ? () => closePane(pane.id) : undefined}
              icon={iconFor(pane.type)}
              label={pane.title}
            />
          ))}
        </div>
      </div>
      {!projectId && <div className="emptyNote">先选择项目</div>}
      {activeView === "files" && (
        <FileTreePanel
          tree={tree}
          selectedPath={selectedPath}
          fileContent={fileContent}
          onRead={onReadFile}
          onOpenExternal={onOpenFileExternal}
        />
      )}
      {activeView === "side_chat" && <SideChatPanel projectId={projectId} />}
      {activeView === "browser" && <BrowserPanel />}
      {activeView === "terminal" && <TerminalPanel projectId={projectId} jobs={jobs} runtime={runtime} onRuntimeChange={onRuntimeChange} />}
      {activeView === "settings" && <SettingsPanel projectId={projectId} runtime={runtime} onRuntimeChange={onRuntimeChange} />}
      {activeView === "events" && <EventTimeline events={events} />}
      {activeView === "subagents" && <SubagentPanel subagents={subagents} />}
    </aside>
  );
}

function MiniTab({
  active,
  onClick,
  onClose,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  onClose?: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <span className={`dockMiniTab ${active ? "is-active" : ""}`}>
      <button className="dockMiniTab__main" onClick={onClick} role="tab" aria-selected={active} title={label}>
        {icon}
        <span>{label}</span>
      </button>
      {onClose && (
        <button
          className="dockMiniTab__close"
          onClick={onClose}
          aria-label={`关闭${label}`}
          title={`关闭${label}`}
          type="button"
        >
          <X size={12} />
        </button>
      )}
    </span>
  );
}

function iconFor(view: DockView): ReactNode {
  return {
    files: <Files size={14} />,
    side_chat: <MessageCirclePlus size={14} />,
    browser: <Globe size={14} />,
    terminal: <SquareTerminal size={14} />,
    settings: <Settings size={14} />,
    events: <Workflow size={14} />,
    subagents: <ListTree size={14} />,
  }[view];
}

function titleFor(view: DockView): string {
  return {
    files: "文件",
    side_chat: "侧边聊天",
    browser: "浏览器",
    terminal: "终端",
    settings: "设置",
    events: "事件",
    subagents: "子任务",
  }[view];
}
