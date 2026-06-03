import type {
  ControllerSnapshot,
  ApprovalInfo,
  AttachmentInfo,
  ApiTestResult,
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
  TerminalSessionInfo,
  Summary,
  TestRun,
  PermissionMode,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const api = {
  async projects(): Promise<Project[]> {
    const data = await request<{ projects: Project[] }>("/api/projects");
    return data.projects;
  },
  async createProject(name: string, rootPath: string): Promise<Project> {
    return request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, root_path: rootPath }),
    });
  },
  pickFolder(): Promise<PickFolderResult> {
    return request<PickFolderResult>("/api/system/pick-folder", { method: "POST", body: "{}" });
  },
  async sessions(projectId: string): Promise<SessionMeta[]> {
    const data = await request<{ sessions: SessionMeta[] }>(`/api/projects/${projectId}/sessions`);
    return data.sessions;
  },
  async createSession(projectId: string, label = "ui"): Promise<{ id: string }> {
    return request<{ id: string }>(`/api/projects/${projectId}/sessions`, {
      method: "POST",
      body: JSON.stringify({ label }),
    });
  },
  async session(projectId: string, sessionId: string): Promise<{ id: string; messages: Message[] }> {
    return request<{ id: string; messages: Message[] }>(`/api/projects/${projectId}/sessions/${sessionId}`);
  },
  async deleteSession(projectId: string, sessionId: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/api/projects/${projectId}/sessions/${sessionId}`, { method: "DELETE" });
  },
  async renameSession(projectId: string, sessionId: string, label: string): Promise<{ renamed: boolean; label: string; id: string }> {
    return request<{ renamed: boolean; label: string; id: string }>(`/api/projects/${projectId}/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify({ label }),
    });
  },
  async send(
    projectId: string,
    sessionId: string,
    message: string,
    plan: boolean,
    permissionMode: PermissionMode,
    attachmentIds: string[] = [],
  ): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/projects/${projectId}/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message, plan, permission_mode: permissionMode, attachment_ids: attachmentIds }),
    });
  },
  async plan(projectId: string, sessionId: string): Promise<{ plan: Summary["pending_plan"] }> {
    return request<{ plan: Summary["pending_plan"] }>(`/api/projects/${projectId}/sessions/${sessionId}/plan`);
  },
  approvePlan(projectId: string, sessionId: string, permissionMode: PermissionMode): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/projects/${projectId}/sessions/${sessionId}/plan/approve`, {
      method: "POST",
      body: JSON.stringify({ permission_mode: permissionMode }),
    });
  },
  refinePlan(projectId: string, sessionId: string, feedback: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/projects/${projectId}/sessions/${sessionId}/plan/refine`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    });
  },
  cancelPlan(projectId: string, sessionId: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/projects/${projectId}/sessions/${sessionId}/plan/cancel`, {
      method: "POST",
      body: "{}",
    });
  },
  async attachments(projectId: string, sessionId: string): Promise<AttachmentInfo[]> {
    const data = await request<{ attachments: AttachmentInfo[] }>(
      `/api/projects/${projectId}/sessions/${sessionId}/attachments`,
    );
    return data.attachments;
  },
  uploadAttachment(
    projectId: string,
    sessionId: string,
    payload: { name: string; content_base64: string; mime_type: string },
  ): Promise<AttachmentInfo> {
    return request<AttachmentInfo>(`/api/projects/${projectId}/sessions/${sessionId}/attachments`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  cancel(projectId: string, sessionId: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/projects/${projectId}/sessions/${sessionId}/cancel`, {
      method: "POST",
      body: "{}",
    });
  },
  controller(projectId: string, sessionId: string): Promise<ControllerSnapshot> {
    return request<ControllerSnapshot>(`/api/projects/${projectId}/sessions/${sessionId}/controller`);
  },
  summary(projectId: string, sessionId: string): Promise<Summary> {
    return request<Summary>(`/api/projects/${projectId}/sessions/${sessionId}/summary`);
  },
  async events(projectId: string, sessionId: string): Promise<RunEvent[]> {
    const data = await request<{ events: RunEvent[] }>(`/api/projects/${projectId}/sessions/${sessionId}/events`);
    return data.events;
  },
  confirmChanges(projectId: string, sessionId: string): Promise<{ status: string }> {
    return request(`/api/projects/${projectId}/sessions/${sessionId}/changes/confirm`, {
      method: "POST",
      body: "{}",
    });
  },
  undoChanges(projectId: string, sessionId: string): Promise<{ status: string }> {
    return request(`/api/projects/${projectId}/sessions/${sessionId}/changes/undo`, {
      method: "POST",
      body: "{}",
    });
  },
  undoChangeFile(projectId: string, sessionId: string, path: string): Promise<{ status: string; path: string }> {
    return request(`/api/projects/${projectId}/sessions/${sessionId}/changes/undo-file`, {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },
  async subagents(projectId: string, sessionId: string): Promise<SubagentInfo[]> {
    const data = await request<{ subagents: SubagentInfo[] }>(`/api/projects/${projectId}/sessions/${sessionId}/subagents`);
    return data.subagents;
  },
  tree(projectId: string): Promise<FileNode> {
    return request<FileNode>(`/api/projects/${projectId}/files/tree?depth=3`);
  },
  readFile(projectId: string, path: string): Promise<{ rel_path: string; content: string; truncated: boolean }> {
    return request(`/api/projects/${projectId}/files/read?path=${encodeURIComponent(path)}`);
  },
  openFile(projectId: string, path: string, app = ""): Promise<{ ok: boolean; reason?: string; command?: string[] }> {
    return request(`/api/projects/${projectId}/files/open`, {
      method: "POST",
      body: JSON.stringify({ path, app }),
    });
  },
  async jobs(projectId: string): Promise<JobInfo[]> {
    const data = await request<{ jobs: JobInfo[] }>(`/api/projects/${projectId}/jobs`);
    return data.jobs;
  },
  settings(projectId: string): Promise<ProjectSettings> {
    return request<ProjectSettings>(`/api/projects/${projectId}/settings`);
  },
  updateSettings(projectId: string, settings: Partial<ProjectSettings>): Promise<ProjectSettings> {
    return request<ProjectSettings>(`/api/projects/${projectId}/settings`, {
      method: "PUT",
      body: JSON.stringify(settings),
    });
  },
  saveApiKey(projectId: string, value: string): Promise<ProjectSettings> {
    return request<ProjectSettings>(`/api/projects/${projectId}/settings/api-key`, {
      method: "POST",
      body: JSON.stringify({ value }),
    });
  },
  clearApiKey(projectId: string): Promise<ProjectSettings> {
    return request<ProjectSettings>(`/api/projects/${projectId}/settings/api-key`, {
      method: "DELETE",
    });
  },
  apiTest(projectId: string, count = 3): Promise<ApiTestResult> {
    return request<ApiTestResult>(`/api/projects/${projectId}/settings/api-test`, {
      method: "POST",
      body: JSON.stringify({ count }),
    });
  },
  policy(projectId: string): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(`/api/projects/${projectId}/settings/policy`);
  },
  updatePolicy(projectId: string, patch: Record<string, unknown>): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(`/api/projects/${projectId}/settings/policy`, {
      method: "PUT",
      body: JSON.stringify(patch),
    });
  },
  runtime(projectId: string): Promise<RuntimeInfo> {
    return request<RuntimeInfo>(`/api/projects/${projectId}/runtime`);
  },
  updateRuntime(projectId: string, patch: { python?: string; shell?: string }): Promise<RuntimeInfo> {
    return request<RuntimeInfo>(`/api/projects/${projectId}/runtime`, {
      method: "POST",
      body: JSON.stringify(patch),
    });
  },
  async terminals(projectId: string): Promise<TerminalSessionInfo[]> {
    const data = await request<{ terminals: TerminalSessionInfo[] }>(`/api/projects/${projectId}/terminals`);
    return data.terminals;
  },
  createTerminal(projectId: string, payload: { kind?: "python" | "shell"; shell?: string; python?: string } = {}): Promise<TerminalSessionInfo> {
    return request<TerminalSessionInfo>(`/api/projects/${projectId}/terminals`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  readTerminal(terminalId: string, cursor: number): Promise<TerminalSessionInfo> {
    return request<TerminalSessionInfo>(`/api/terminals/${terminalId}/read?cursor=${cursor}`);
  },
  writeTerminal(terminalId: string, data: string): Promise<TerminalSessionInfo> {
    return request<TerminalSessionInfo>(`/api/terminals/${terminalId}/input`, {
      method: "POST",
      body: JSON.stringify({ data }),
    });
  },
  closeTerminal(terminalId: string): Promise<TerminalSessionInfo> {
    return request<TerminalSessionInfo>(`/api/terminals/${terminalId}/close`, {
      method: "POST",
      body: "{}",
    });
  },
  runTest(projectId: string, label: string): Promise<TestRun> {
    return request<TestRun>(`/api/projects/${projectId}/tests/run`, {
      method: "POST",
      body: JSON.stringify({ label }),
    });
  },
  getTest(projectId: string, runId: string): Promise<TestRun> {
    return request<TestRun>(`/api/projects/${projectId}/tests/${runId}`);
  },
  async approvals(sessionId = ""): Promise<ApprovalInfo[]> {
    const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const data = await request<{ approvals: ApprovalInfo[] }>(`/api/approvals${suffix}`);
    return data.approvals;
  },
  decideApproval(approvalId: string, approved: boolean): Promise<{ id: string; status: string; approved: boolean }> {
    return request(`/api/approvals/${approvalId}`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    });
  },
};
