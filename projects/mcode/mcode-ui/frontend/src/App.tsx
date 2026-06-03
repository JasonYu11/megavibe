import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "./api/client";
import { startRunEventStream } from "./api/stream";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { ProjectPickerDialog } from "./components/ProjectPickerDialog";
import { ProjectSidebar } from "./components/ProjectSidebar";
import { WorkspaceDock } from "./components/WorkspaceDock";
import type { DockView } from "./components/WorkspaceDock";
import { LAYOUT_STORAGE_KEY, clampLayout, computeWorkbenchLayout, parseLayout } from "./layoutState";
import { itemsFromMessagesAndEvents } from "./state/events";
import type {
  ControllerSnapshot,
  ApprovalInfo,
  AttachmentInfo,
  FileNode,
  JobInfo,
  Message,
  PickFolderResult,
  Project,
  ProjectSettings,
  RunEvent,
  RuntimeInfo,
  SessionMeta,
  SubagentInfo,
  Summary,
  TestRun,
  UiItem,
  PermissionMode,
} from "./types";

type AppStatus = "idle" | "creating_session" | "sending" | "running" | "cancelling" | "failed";

interface PendingMessage {
  id: string;
  text: string;
  status: "pending" | "sent" | "failed";
  error?: string;
}

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

const BUILTIN_SKILLS = [
  { name: "test", description: "运行测试套件，诊断失败，修复后重跑直到通过", run_as: "inline" },
  { name: "init", description: "分析项目结构，生成 MEMORY.md 项目指南", run_as: "inline" },
  { name: "explore", description: "只读代码库探索，返回分析摘要和文件引用", run_as: "subagent" },
  { name: "review", description: "审查当前变更：正确性、风险、缺失测试", run_as: "subagent" },
  { name: "security-review", description: "安全检查：注入、鉴权、密钥、路径穿越等", run_as: "subagent" },
];

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [controller, setController] = useState<ControllerSnapshot | null>(null);
  const [tree, setTree] = useState<FileNode | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [fileContent, setFileContent] = useState<string>("");
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [projectSettings, setProjectSettings] = useState<ProjectSettings | null>(null);
  const [subagents, setSubagents] = useState<SubagentInfo[]>([]);
  const [approvals, setApprovals] = useState<ApprovalInfo[]>([]);
  const [draftAttachments, setDraftAttachments] = useState<AttachmentInfo[]>([]);
  const [testRun, setTestRun] = useState<TestRun | null>(null);
  const [plan, setPlan] = useState(false);
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("auto_review");
  const [status, setStatus] = useState<AppStatus>("idle");
  const sessionGenerationRef = useRef(0);
  const [error, setError] = useState("");
  const [pollFailures, setPollFailures] = useState(0);
  const [streamActive, setStreamActive] = useState(false);
  const [pendingMessages, setPendingMessages] = useState<PendingMessage[]>([]);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [dockView, setDockView] = useState<DockView>("files");
  const [layout, setLayout] = useState(() =>
    parseLayout(typeof window === "undefined" ? null : window.localStorage.getItem(LAYOUT_STORAGE_KEY)),
  );
  const shellRef = useRef<HTMLDivElement>(null);
  const [shellWidth, setShellWidth] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));
  const [pickedFolder, setPickedFolder] = useState<PickFolderResult | null>(null);
  const [pickerBusy, setPickerBusy] = useState(false);
  const [pickerError, setPickerError] = useState("");
  const lastEventSeqRef = useRef(0);

  const currentProject = projects.find((project) => project.id === projectId);
  const currentSession = sessions.find((session) => session.id === sessionId);
  const persistedItems = useMemo(() => itemsFromMessagesAndEvents(messages, events), [messages, events]);
  const items: UiItem[] = useMemo(() => {
    const persistedUserTexts = new Set(
      persistedItems.filter((item) => item.kind === "user").map((item) => item.text),
    );
    return [
      ...persistedItems,
      ...pendingMessages
        .filter((message) => !persistedUserTexts.has(message.text))
        .map((message) => ({
          kind: "user" as const,
          id: message.id,
          text: message.text,
          status: message.status === "pending" || message.status === "failed" ? message.status : undefined,
          error: message.error,
          canRetry: message.status === "failed",
        })),
    ];
  }, [pendingMessages, persistedItems]);
  const backendRunning =
    controller?.running ||
    summary?.status === "running" ||
    summary?.status === "tool_running" ||
    summary?.status === "subagent_running" ||
    summary?.status === "compacting" ||
    summary?.status === "cancelling" ||
    summary?.status === "waiting_approval";
  const running = backendRunning || status === "sending" || status === "running" || status === "cancelling";
  const resolvedLayout = useMemo(() => computeWorkbenchLayout({ layout, containerWidth: shellWidth }), [layout, shellWidth]);

  useEffect(() => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  }, [layout]);

  useEffect(() => {
    const node = shellRef.current;
    if (!node) return;
    const updateWidth = () => setShellWidth(Math.round(node.getBoundingClientRect().width || window.innerWidth));
    updateWidth();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateWidth);
      return () => window.removeEventListener("resize", updateWidth);
    }
    const observer = new ResizeObserver(updateWidth);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const clearProjectView = useCallback(() => {
    setSessionId("");
    setSessions([]);
    setMessages([]);
    setEvents([]);
    setSummary(null);
    setController(null);
    setSubagents([]);
    setApprovals([]);
    setDraftAttachments([]);
    setJobs([]);
    setRuntimeInfo(null);
    setProjectSettings(null);
    setTree(null);
    setSelectedFile("");
    setFileContent("");
    setPendingMessages([]);
    setPollFailures(0);
    setStatus("idle");
  }, []);

  const refreshProjects = useCallback(async () => {
    const rows = await api.projects();
    setProjects(rows);
    setProjectId((current) => current || rows[0]?.id || "");
  }, []);

  const refreshProjectData = useCallback(async () => {
    if (!projectId) return;
    const [sessionResult, treeResult, jobsResult, runtimeResult, settingsResult] = await Promise.allSettled([
      api.sessions(projectId),
      api.tree(projectId),
      api.jobs(projectId),
      api.runtime(projectId),
      api.settings(projectId),
    ]);
    if (sessionResult.status === "fulfilled") {
      setSessions(sessionResult.value);
      setSessionId((current) => current || sessionResult.value[0]?.id || "");
    }
    if (treeResult.status === "fulfilled") setTree(treeResult.value);
    if (jobsResult.status === "fulfilled") setJobs(jobsResult.value);
    if (runtimeResult.status === "fulfilled") setRuntimeInfo(runtimeResult.value);
    if (settingsResult.status === "fulfilled") setProjectSettings(settingsResult.value);
    const failed = [sessionResult, treeResult, jobsResult, runtimeResult, settingsResult].filter((item) => item.status === "rejected");
    if (failed.length) setError(`项目刷新部分失败：${String((failed[0] as PromiseRejectedResult).reason)}`);
  }, [projectId]);

  const refreshSessionData = useCallback(async () => {
    if (!projectId || !sessionId) return;
    const generation = sessionGenerationRef.current;
    const [sessionResult, eventResult, summaryResult, subagentResult, jobResult, controllerResult, approvalResult] = await Promise.allSettled([
      api.session(projectId, sessionId),
      api.events(projectId, sessionId),
      api.summary(projectId, sessionId),
      api.subagents(projectId, sessionId),
      api.jobs(projectId),
      api.controller(projectId, sessionId),
      api.approvals(sessionId),
    ]);
    let failures = 0;
    if (sessionResult.status === "fulfilled") {
      if (sessionGenerationRef.current !== generation) return;
      const sessionMessages = sessionResult.value.messages;
      setMessages(sessionMessages);
      setPendingMessages((pending) =>
        pending.filter(
          (item) =>
            item.status === "failed" ||
            (item.status === "pending" && !sessionMessages.some((message) => message.role === "user" && message.content === item.text)),
        ),
      );
    } else {
      failures += 1;
    }
    if (eventResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setEvents((current) => mergeRunEvents(current, eventResult.value)); }
    else failures += 1;
    if (summaryResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setSummary(summaryResult.value); }
    else failures += 1;
    if (subagentResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setSubagents(subagentResult.value); }
    else failures += 1;
    if (jobResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setJobs(jobResult.value); }
    else failures += 1;
    if (controllerResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setController(controllerResult.value); }
    else failures += 1;
    if (approvalResult.status === "fulfilled") { if (sessionGenerationRef.current === generation) setApprovals(approvalResult.value); }
    else failures += 1;

    if (failures) {
      setPollFailures((count) => {
        const next = count + 1;
        if (next >= 3) setError("连接后端失败，已保留当前 transcript");
        return next;
      });
      return;
    }
    if (sessionGenerationRef.current !== generation) return;
    setPollFailures(0);
    const latestSummary = summaryResult.status === "fulfilled" ? summaryResult.value : null;
    const latestController = controllerResult.status === "fulfilled" ? controllerResult.value : null;
    const latestRunning =
      latestController?.running ||
      latestSummary?.status === "running" ||
      latestSummary?.status === "tool_running" ||
      latestSummary?.status === "subagent_running" ||
      latestSummary?.status === "compacting" ||
      latestSummary?.status === "cancelling" ||
      latestSummary?.status === "waiting_approval";
    setStatus((current) => {
      if (current === "failed" && latestRunning) return current;
      return latestRunning ? "running" : "idle";
    });
  }, [projectId, sessionId]);

  useEffect(() => {
    void refreshProjects().catch((exc) => setError(String(exc)));
  }, [refreshProjects]);

  useEffect(() => {
    void refreshProjectData().catch((exc) => setError(String(exc)));
  }, [refreshProjectData]);

  // Clear state on session switch and bump generation to reject in-flight requests
  useEffect(() => {
    sessionGenerationRef.current += 1;
    setMessages([]);
    setEvents([]);
    setSummary(null);
    setController(null);
    setSubagents([]);
    setApprovals([]);
    setJobs([]);
    setPendingMessages([]);
    setPollFailures(0);
    setStatus("idle");
  }, [sessionId]);

  useEffect(() => {
    void refreshSessionData().catch((exc) => setError(String(exc)));
    const id = window.setInterval(() => void refreshSessionData().catch((exc) => setError(String(exc))), streamActive ? 1500 : 500);
    return () => window.clearInterval(id);
  }, [refreshSessionData, streamActive]);

  useEffect(() => {
    lastEventSeqRef.current = events.reduce((max, event) => Math.max(max, Number(event.seq ?? 0) || 0), 0);
  }, [events]);

  useEffect(() => {
    if (!projectId || !sessionId || typeof EventSource === "undefined") {
      setStreamActive(false);
      return;
    }
    const stream = startRunEventStream({
      projectId,
      sessionId,
      getLastSeq: () => lastEventSeqRef.current,
      onOpen: () => setStreamActive(true),
      onError: () => setStreamActive(false),
      onEvent: (record) => {
        setEvents((current) => mergeRunEvents(current, [record]));
        const seq = Number(record.seq ?? 0) || 0;
        if (seq > lastEventSeqRef.current) lastEventSeqRef.current = seq;
      },
    });
    return () => {
      stream.close();
      setStreamActive(false);
    };
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!testRun || testRun.status !== "running" || !projectId) return;
    const id = window.setInterval(async () => {
      const next = await api.getTest(projectId, testRun.id);
      setTestRun(next);
      if (next.status !== "running") window.clearInterval(id);
    }, 600);
    return () => window.clearInterval(id);
  }, [projectId, testRun]);

  const selectProject = (id: string) => {
    setProjectId(id);
    clearProjectView();
  };

  const pickFolder = async () => {
    setPickerBusy(true);
    setPickerError("");
    try {
      const picked = await api.pickFolder();
      setPickedFolder(picked);
      if (picked.cancelled) setPickerError(picked.reason || "已取消选择");
    } catch (exc) {
      setPickerError(String(exc));
    } finally {
      setPickerBusy(false);
    }
  };

  const createProject = async (name: string, rootPath: string) => {
    if (!rootPath.trim()) return;
    setPickerBusy(true);
    setPickerError("");
    try {
      const project = await api.createProject(name, rootPath);
      const rows = await api.projects();
      setProjects(rows);
      setProjectDialogOpen(false);
      setPickedFolder(null);
      clearProjectView();
      setProjectId(project.id);
    } catch (exc) {
      setPickerError(String(exc));
    } finally {
      setPickerBusy(false);
    }
  };

  const createSession = async () => {
    if (!projectId) return "";
    setStatus("creating_session");
    const session = await api.createSession(projectId);
    setSessionId(session.id);
    setMessages([]);
    setEvents([]);
    setSummary({ run_id: session.id, status: "created" });
    setController(null);
    setSubagents([]);
    setApprovals([]);
    setPendingMessages([]);
    const sessionRows = await api.sessions(projectId);
    setSessions(sessionRows);
    setStatus("idle");
    return session.id;
  };

  const deleteSession = async (id: string) => {
    if (!projectId) return;
    await api.deleteSession(projectId, id);
    if (id === sessionId) { setSessionId(""); setMessages([]); setEvents([]); }
    const rows = await api.sessions(projectId);
    setSessions(rows);
  };

  const renameSession = async (id: string, label: string) => {
    if (!projectId) return;
    const result = await api.renameSession(projectId, id, label);
    // The rename creates a new session ID — switch to it if this was the active session
    if (id === sessionId) setSessionId(result.id);
    const rows = await api.sessions(projectId);
    setSessions(rows);
  };

  const send = async (text: string) => {
    if (!projectId || !text.trim()) return;
    const pendingId = `pending-${Date.now()}`;
    let targetSession = sessionId;
    setError("");
    try {
      if (!targetSession) targetSession = await createSession();
      if (!targetSession) throw new Error("无法创建会话");
      setStatus("sending");
      setPendingMessages((prev) => [...prev, { id: pendingId, text, status: "pending" }]);
      await api.send(
        projectId,
        targetSession,
        text,
        plan,
        permissionMode,
        draftAttachments.filter((attachment) => !attachment.upload_status || attachment.upload_status === "uploaded").map((attachment) => attachment.id),
      );
      setPendingMessages((prev) => prev.map((item) => (item.id === pendingId ? { ...item, status: "sent" } : item)));
      setDraftAttachments([]);
      setStatus("running");
      await refreshSessionData();
      await refreshProjectData();
    } catch (exc) {
      const message = String(exc);
      setStatus("failed");
      setPendingMessages((prev) =>
        prev.map((item) => (item.id === pendingId ? { ...item, status: "failed", error: message } : item)),
      );
      setError(message);
    }
  };

  const retrySend = async (text: string) => {
    setPendingMessages((prev) => prev.filter((item) => !(item.text === text && item.status === "failed")));
    await send(text);
  };

  const cancel = async () => {
    if (!projectId || !sessionId) return;
    setStatus("cancelling");
    await api.cancel(projectId, sessionId);
    setSummary((prev) => ({ ...(prev ?? {}), status: "cancelling" }));
    await refreshSessionData();
  };

  const decideApproval = async (approvalId: string, approved: boolean) => {
    await api.decideApproval(approvalId, approved);
    if (sessionId) setApprovals(await api.approvals(sessionId));
  };

  const approvePlan = async () => {
    if (!projectId || !sessionId) return;
    setPlan(false);
    setStatus("sending");
    await api.approvePlan(projectId, sessionId, permissionMode);
    setStatus("running");
    await refreshSessionData();
  };

  const refinePlan = async (feedback: string) => {
    if (!projectId || !sessionId || !feedback.trim()) return;
    setPlan(true);
    setStatus("sending");
    await api.refinePlan(projectId, sessionId, feedback);
    setStatus("running");
    await refreshSessionData();
  };

  const cancelPlan = async () => {
    if (!projectId || !sessionId) return;
    await api.cancelPlan(projectId, sessionId);
    setPlan(false);
    await refreshSessionData();
  };

  const confirmChanges = async () => {
    if (!projectId || !sessionId) return;
    await api.confirmChanges(projectId, sessionId);
    await refreshSessionData();
  };

  const undoChanges = async () => {
    if (!projectId || !sessionId) return;
    await api.undoChanges(projectId, sessionId);
    await refreshSessionData();
    await refreshProjectData();
  };

  const undoChangeFile = async (path: string) => {
    if (!projectId || !sessionId) return;
    await api.undoChangeFile(projectId, sessionId, path);
    await refreshSessionData();
    await refreshProjectData();
  };

  const readFile = async (path: string) => {
    if (!projectId) return;
    const data = await api.readFile(projectId, path);
    setSelectedFile(data.rel_path);
    setFileContent(data.content);
  };

  const openFileExternal = async (path: string, app = "") => {
    if (!projectId) return;
    await api.openFile(projectId, path, app || projectSettings?.ui.file_open_app || "");
  };

  const attachFiles = async (files: FileList) => {
    if (!projectId) return;
    let targetSession = sessionId;
    if (!targetSession) targetSession = await createSession();
    if (!targetSession) throw new Error("无法创建会话");
    for (const file of Array.from(files)) {
      const localId = `local_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      const placeholder: AttachmentInfo = {
        id: localId,
        session_id: targetSession,
        name: file.name,
        size: file.size,
        mime_type: file.type || "",
        preview: "",
        is_image: file.type.startsWith("image/"),
        is_text: file.type.startsWith("text/") || /\.(txt|md|py|ts|tsx|js|json|yaml|yml|csv|sh|go|rs)$/i.test(file.name),
        preview_available: false,
        upload_status: "uploading",
        local_file: file,
        created_at: Date.now() / 1000,
      };
      setDraftAttachments((current) => [...current, placeholder]);
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setDraftAttachments((current) =>
          current.map((attachment) =>
            attachment.id === localId
              ? { ...attachment, upload_status: "failed", error: `文件超过最大限制 ${formatBytes(MAX_ATTACHMENT_BYTES)}` }
              : attachment,
          ),
        );
        continue;
      }
      await uploadAttachmentFile(projectId, targetSession, localId, file);
    }
  };

  const retryAttachment = async (id: string) => {
    if (!projectId) return;
    const attachment = draftAttachments.find((item) => item.id === id);
    if (!attachment?.local_file) return;
    setDraftAttachments((current) =>
      current.map((item) => (item.id === id ? { ...item, upload_status: "uploading", error: "" } : item)),
    );
    let targetSession = attachment.session_id || sessionId;
    if (!targetSession) targetSession = await createSession();
    await uploadAttachmentFile(projectId, targetSession, id, attachment.local_file);
  };

  const uploadAttachmentFile = async (targetProjectId: string, targetSession: string, localId: string, file: File) => {
    try {
      const content_base64 = await fileToBase64(file);
      const uploaded = await api.uploadAttachment(targetProjectId, targetSession, {
        name: file.name,
        mime_type: file.type || "",
        content_base64,
      });
      setDraftAttachments((current) =>
        current.map((attachment) =>
          attachment.id === localId ? { ...uploaded, upload_status: "uploaded", local_file: file } : attachment,
        ),
      );
    } catch (exc) {
      setDraftAttachments((current) =>
        current.map((attachment) =>
          attachment.id === localId ? { ...attachment, upload_status: "failed", error: String(exc) } : attachment,
        ),
      );
    }
  };

  const updateRuntime = async (patch: { python?: string; shell?: string }) => {
    if (!projectId) return;
    const next = await api.updateRuntime(projectId, patch);
    setRuntimeInfo(next);
  };

  const updateModel = async (model: string, thinkingMode: boolean) => {
    if (!projectId || !projectSettings) return;
    const next = await api.updateSettings(projectId, {
      provider: { ...projectSettings.provider, model, thinking_mode: thinkingMode },
    });
    setProjectSettings(next);
  };

  const runTest = async (label = "product") => {
    if (!projectId) return;
    const run = await api.runTest(projectId, label);
    setTestRun(run);
  };

  const startResize = (side: "left" | "right", event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startLayout = layout;
    const onMove = (moveEvent: MouseEvent) => {
      const delta = moveEvent.clientX - startX;
      document.body.classList.add("is-resizing");
      setLayout((current) =>
        clampLayout({
          ...current,
          leftWidth: side === "left" ? startLayout.leftWidth + delta : current.leftWidth,
          rightWidth: side === "right" ? startLayout.rightWidth - delta : current.rightWidth,
        }),
      );
    };
    const onUp = () => {
      document.body.classList.remove("is-resizing");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    document.body.classList.add("is-resizing");
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  useEffect(() => {
    const titleParts = [currentProject?.name || "Mcode"];
    if (currentSession?.preview) titleParts.unshift(currentSession.preview);
    document.title = `${titleParts.join(" - ")} - Mcode`;
  }, [currentProject?.name, currentSession?.preview]);

  useEffect(() => {
    const onNativeAction = (event: Event) => {
      const detail = (event as CustomEvent<{ type?: string; projectId?: string; rootPath?: string; message?: string }>).detail || {};
      if (detail.type === "open-settings") {
        setDockView("settings");
        return;
      }
      if (detail.type === "new-session") {
        void createSession().catch((exc) => setError(String(exc)));
        return;
      }
      if (detail.type === "project-opened") {
        void (async () => {
          const rows = await api.projects();
          setProjects(rows);
          const nextId = detail.projectId || rows.find((project) => project.root_path === detail.rootPath)?.id || rows[0]?.id || "";
          if (nextId) {
            clearProjectView();
            setProjectId(nextId);
          }
        })().catch((exc) => setError(String(exc)));
        return;
      }
      if (detail.type === "error") {
        setError(detail.message || "Native action failed");
      }
    };
    window.addEventListener("mcode:native-action", onNativeAction);
    return () => window.removeEventListener("mcode:native-action", onNativeAction);
  }, [clearProjectView, createSession]);

  return (
    <div
      ref={shellRef}
      className={`appShell ${!resolvedLayout.leftVisible ? "is-leftCollapsed" : ""} ${!resolvedLayout.rightVisible ? "is-rightCollapsed" : ""}`}
      style={
        {
          "--layout-columns": resolvedLayout.columns,
          "--left-width": `${resolvedLayout.leftWidth}px`,
          "--right-width": `${resolvedLayout.rightWidth}px`,
          "--main-width": `${resolvedLayout.mainWidth}px`,
          "--main-min-width": `${resolvedLayout.mainMinWidth}px`,
        } as CSSProperties
      }
    >
      {!resolvedLayout.leftVisible ? (
        <button
          className="layoutRail layoutRail--left"
          onClick={() => setLayout((current) => ({ ...current, leftCollapsed: false }))}
          title="显示项目侧栏"
        >
          项目
        </button>
      ) : (
        <ProjectSidebar
          projects={projects}
          sessions={sessions}
          selectedProjectId={projectId}
          selectedSessionId={sessionId}
          selectedProjectRoot={currentProject?.root_path}
          onSelectProject={selectProject}
          onSelectSession={setSessionId}
          onNewSession={() => void createSession().catch((exc) => setError(String(exc)))}
          onCreateProject={() => setProjectDialogOpen(true)}
          onOpenSettings={() => setDockView("settings")}
          onDeleteSession={(id) => void deleteSession(id).catch((exc) => setError(String(exc)))}
          onRenameSession={(id, label) => void renameSession(id, label).catch((exc) => setError(String(exc)))}
        />
      )}
      {resolvedLayout.leftVisible && (
        <button
          className="layoutHandle layoutHandle--left"
          onMouseDown={(event) => startResize("left", event)}
          onDoubleClick={() => setLayout((current) => ({ ...current, leftCollapsed: true }))}
          title="拖动调整项目侧栏，双击隐藏"
          aria-label="调整项目侧栏宽度"
        />
      )}
      <ChatWorkspace
        title={currentSession?.preview || currentProject?.name || "Mcode"}
        projectRoot={controller?.root || currentProject?.root_path}
        sessionId={sessionId}
        appStatus={status}
        items={items}
        summary={summary}
        running={Boolean(running)}
        plan={plan}
        permissionMode={permissionMode}
        model={projectSettings?.provider.model}
        thinkingMode={Boolean(projectSettings?.provider.thinking_mode)}
        attachments={draftAttachments}
        onPlanChange={setPlan}
        onPermissionModeChange={setPermissionMode}
        onModelChange={(model, thinkingMode) => void updateModel(model, thinkingMode).catch((exc) => setError(String(exc)))}
        onAttachFiles={(files) => void attachFiles(files).catch((exc) => setError(String(exc)))}
        onRemoveAttachment={(id) => setDraftAttachments((current) => current.filter((attachment) => attachment.id !== id))}
        onRetryAttachment={(id) => void retryAttachment(id).catch((exc) => setError(String(exc)))}
        onSend={(text) => void send(text)}
        onCancel={() => void cancel().catch((exc) => setError(String(exc)))}
        onRetry={(text) => void retrySend(text).catch((exc) => setError(String(exc)))}
        onApprovePlan={() => void approvePlan().catch((exc) => setError(String(exc)))}
        onRefinePlan={(feedback) => void refinePlan(feedback).catch((exc) => setError(String(exc)))}
        onCancelPlan={() => void cancelPlan().catch((exc) => setError(String(exc)))}
        onConfirmChanges={() => void confirmChanges().catch((exc) => setError(String(exc)))}
        onUndoChanges={() => void undoChanges().catch((exc) => setError(String(exc)))}
        onUndoChangeFile={(path) => void undoChangeFile(path).catch((exc) => setError(String(exc)))}
        onOpenFile={(path) => void readFile(path).catch((exc) => setError(String(exc)))}
        approvals={approvals}
        onApprovalDecision={(approvalId, approved) => void decideApproval(approvalId, approved).catch((exc) => setError(String(exc)))}
        skills={BUILTIN_SKILLS}
        onSkillSelect={(name) => void send(`/skill ${name}`)}
      />
      {resolvedLayout.rightVisible && (
        <button
          className="layoutHandle layoutHandle--right"
          onMouseDown={(event) => startResize("right", event)}
          onDoubleClick={() => setLayout((current) => ({ ...current, rightCollapsed: true }))}
          title="拖动调整工作区 Dock，双击隐藏"
          aria-label="调整工作区 Dock 宽度"
        />
      )}
      {!resolvedLayout.rightVisible ? (
        <button
          className="layoutRail layoutRail--right"
          onClick={() => setLayout((current) => ({ ...current, rightCollapsed: false }))}
          title="显示工作区 Dock"
        >
          Dock
        </button>
      ) : (
        <WorkspaceDock
          tree={tree}
          selectedPath={selectedFile}
          fileContent={fileContent}
          events={events}
          jobs={jobs}
          subagents={subagents}
          runtime={runtimeInfo}
          projectId={projectId}
          view={dockView}
          onViewChange={setDockView}
          onHide={() => setLayout((current) => ({ ...current, rightCollapsed: true }))}
          onReadFile={(path) => void readFile(path).catch((exc) => setError(String(exc)))}
          onOpenFileExternal={(path, app) => void openFileExternal(path, app).catch((exc) => setError(String(exc)))}
          onRuntimeChange={(patch) => void updateRuntime(patch).catch((exc) => setError(String(exc)))}
        />
      )}
      <ProjectPickerDialog
        open={projectDialogOpen}
        busy={pickerBusy}
        picked={pickedFolder}
        error={pickerError}
        onPickFolder={() => void pickFolder()}
        onCreate={(name, rootPath) => void createProject(name, rootPath)}
        onClose={() => setProjectDialogOpen(false)}
      />
      {error && (
        <button className="errorToast" onClick={() => setError("")}>
          {error}
        </button>
      )}
    </div>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("failed to read file"));
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 102.4) / 10} KB`;
  return `${Math.round(size / 1024 / 102.4) / 10} MB`;
}

function mergeRunEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  if (!incoming.length) return current;
  const bySeq = new Map<string, RunEvent>();
  for (const event of current) bySeq.set(eventKey(event), event);
  for (const event of incoming) bySeq.set(eventKey(event), event);
  return Array.from(bySeq.values()).sort((a, b) => {
    const left = Number(a.seq ?? 0) || 0;
    const right = Number(b.seq ?? 0) || 0;
    if (left !== right) return left - right;
    return eventKey(a).localeCompare(eventKey(b));
  });
}

function eventKey(event: RunEvent): string {
  if (event.seq !== undefined) return `seq-${event.seq}`;
  return `${event.kind}-${JSON.stringify(event.data)}`;
}
