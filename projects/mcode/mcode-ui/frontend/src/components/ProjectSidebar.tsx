import { Folder, MessageSquarePlus, Pencil, Plus, Search, Settings, Trash2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { Project, SessionMeta } from "../types";

export function ProjectSidebar({
  projects,
  sessions,
  selectedProjectId,
  selectedSessionId,
  selectedProjectRoot,
  onSelectProject,
  onSelectSession,
  onNewSession,
  onCreateProject,
  onOpenSettings,
  onDeleteSession,
  onRenameSession,
}: {
  projects: Project[];
  sessions: SessionMeta[];
  selectedProjectId?: string;
  selectedSessionId?: string;
  selectedProjectRoot?: string;
  onSelectProject: (id: string) => void;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onCreateProject: () => void;
  onOpenSettings?: () => void;
  onDeleteSession?: (id: string) => void;
  onRenameSession?: (id: string, label: string) => void;
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredProjects = useMemo(
    () =>
      normalizedQuery
        ? projects.filter((project) =>
            [project.name, project.root_path].some((value) => value.toLowerCase().includes(normalizedQuery)),
          )
        : projects,
    [normalizedQuery, projects],
  );
  const filteredSessions = useMemo(
    () =>
      normalizedQuery
        ? sessions.filter((session) =>
            [session.preview, session.id, session.path].some((value) => (value || "").toLowerCase().includes(normalizedQuery)),
          )
        : sessions,
    [normalizedQuery, sessions],
  );

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  return (
    <aside className="sidebar" data-testid="project-sidebar">
      <div className="brandBlock" aria-label="Mcode">
        <img src="/mcode-logo.jpg" alt="" />
        <div>
          <strong>Mcode</strong>
          <span>powered by megawave</span>
        </div>
      </div>
      <div className="sidebar__actions">
        <button className="sidebar__action" onClick={onNewSession}>
          <MessageSquarePlus size={17} /> 新对话
        </button>
        <button className="iconButton" onClick={onCreateProject} title="添加项目" aria-label="添加项目">
          <Plus size={16} />
        </button>
      </div>
      <div className="searchBox">
        <Search size={15} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索"
          aria-label="搜索项目和对话"
        />
      </div>
      <div className="sidebar__section">项目{normalizedQuery ? ` ${filteredProjects.length}` : ""}</div>
      {selectedProjectRoot && <div className="projectRoot" title={selectedProjectRoot}>{selectedProjectRoot}</div>}
      <div className="projectList">
        {filteredProjects.map((project) => (
          <button
            key={project.id}
            className={`projectItem ${project.id === selectedProjectId ? "is-active" : ""}`}
            onClick={() => onSelectProject(project.id)}
          >
            <Folder size={15} />
            <span>{project.name}</span>
          </button>
        ))}
        {filteredProjects.length === 0 && <div className="emptyNote">无匹配项目</div>}
      </div>
      <div className="sidebar__section">对话{normalizedQuery ? ` ${filteredSessions.length}` : ""}</div>
      <div className="sessionList">
        {filteredSessions.map((session) => (
          <div
            key={session.id}
            className={`sessionItem ${session.id === selectedSessionId ? "is-active" : ""}`}
          >
            {renamingId === session.id ? (
              <input
                ref={renameInputRef}
                className="sessionItem__rename"
                defaultValue={session.preview || session.id}
                onBlur={(e) => {
                  const label = e.target.value.trim();
                  if (label && label !== (session.preview || session.id)) {
                    onRenameSession?.(session.id, label);
                  }
                  setRenamingId(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  if (e.key === "Escape") setRenamingId(null);
                }}
                autoFocus
              />
            ) : (
              <button className="sessionItem__main" onClick={() => onSelectSession(session.id)}>
                <span className="sessionItem__title">{session.preview || session.id}</span>
                <span className="sessionItem__meta">{session.messages} 条</span>
              </button>
            )}
            {!renamingId && (
              <div className="sessionItem__actions">
                <button
                  className="sessionItem__action"
                  onClick={(e) => { e.stopPropagation(); setRenamingId(session.id); setTimeout(() => renameInputRef.current?.select(), 0); }}
                  title="重命名"
                >
                  <Pencil size={13} />
                </button>
                <button
                  className="sessionItem__action sessionItem__action--danger"
                  onClick={(e) => { e.stopPropagation(); onDeleteSession?.(session.id); }}
                  title="删除"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            )}
          </div>
        ))}
        {filteredSessions.length === 0 && <div className="emptyNote">{normalizedQuery ? "无匹配对话" : "暂无对话"}</div>}
      </div>
      {onOpenSettings && (
        <button className="sidebar__settings" onClick={onOpenSettings} title="设置">
          <Settings size={15} />
          <span>设置</span>
        </button>
      )}
    </aside>
  );
}
