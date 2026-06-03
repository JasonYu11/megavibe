export interface Project {
  id: string;
  name: string;
  root_path: string;
  created_at: number;
  created?: boolean;
}

export type PermissionMode = "default" | "auto_review" | "full_access";

export interface AttachmentInfo {
  id: string;
  session_id: string;
  name: string;
  size: number;
  mime_type: string;
  preview: string;
  path?: string;
  is_image?: boolean;
  is_text?: boolean;
  preview_available?: boolean;
  data_url?: string;
  upload_status?: "uploading" | "uploaded" | "failed";
  error?: string;
  local_file?: File;
  created_at: number;
}

export interface PickFolderResult {
  cancelled: boolean;
  root_path?: string;
  name?: string;
  reason?: string;
}

export interface ControllerSnapshot {
  session_id: string;
  root: string;
  running: boolean;
  cancel_requested: boolean;
  started_at: number;
  updated_at: number;
}

export interface ApprovalInfo {
  id: string;
  session_id: string;
  tool_name: string;
  arguments: unknown;
  reason: string;
  status: string;
  created_at: number;
  decided_at: number;
  approved: boolean;
}

export interface PendingPlan {
  status: string;
  plan_text: string;
  revision?: number;
  todo_count?: number;
  todos?: Array<{ content?: string; status?: string; level?: number }>;
  created_at?: number;
  created_at_text?: string;
  approved_at?: number;
  approved_at_text?: string;
  cancelled_at?: number;
  cancelled_at_text?: string;
}

export interface SessionMeta {
  id: string;
  path: string;
  messages: number;
  updated_at: number;
  preview: string;
}

export interface Message {
  role: string;
  content: string;
  tool_call_id?: string;
  name?: string;
  tool_calls?: Array<{ id: string; name: string; arguments: unknown }>;
}

export interface RunEvent {
  seq?: number;
  time?: number;
  time_text?: string;
  kind: string;
  data: Record<string, unknown>;
}

export interface Summary {
  run_id?: string;
  status?: string;
  current_tool?: unknown;
  todo?: unknown;
  git?: unknown;
  jobs?: Record<string, unknown>;
  subagents?: Record<string, unknown>;
  final_answer?: string;
  pending_plan?: PendingPlan | null;
  last_error?: string;
  last_notice?: string;
  provider_error?: unknown;
  recoverable?: boolean;
  recent_events?: RunEvent[];
}

export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children: FileNode[];
}

export interface JobInfo {
  job_id: string;
  kind?: string;
  path: string;
  updated_at: number;
  tail: string;
}

export interface RuntimeCandidate {
  path: string;
  label: string;
  source: string;
  selected: boolean;
}

export interface RuntimeInfo {
  shell: string;
  python: string;
  python_source: string;
  candidates: RuntimeCandidate[];
}

export interface ProjectSettings {
  provider: {
    base_url: string;
    model: string;
    thinking_mode: boolean;
    temperature: number;
    timeout_seconds: number;
    max_retries: number;
    proxy_url: string;
    trust_env: boolean;
  };
  agent: {
    max_steps: number;
  };
  context: {
    context_window_tokens: number;
    compact_ratio: number;
    chars_per_token: number;
    recent_keep: number;
    auto_compact: boolean;
    summary_mode: string;
    target_summary_ratio: number;
    min_summary_tokens: number;
    max_summary_tokens: number;
  };
  paths: Record<string, unknown>;
  runtime: {
    shell: string;
    python: string;
    python_preference: string;
  };
  ui: {
    language: string;
    theme: string;
    file_open_app: string;
    show_thought_summary: boolean;
  };
  auto_review: {
    enabled: boolean;
    model: string;
    temperature: number;
    skip_tools: string[];
    always_escalate: string[];
    strictness: Record<string, string>;
  };
  api_key_configured: boolean;
}

export interface ApiTestResult {
  summary: {
    total: number;
    ok: number;
    failed: number;
    errors: Record<string, number>;
    min_seconds?: number;
    median_seconds?: number;
    p95_seconds?: number;
    max_seconds?: number;
  };
  results: Array<{
    index: number;
    ok: boolean;
    elapsed_seconds: number;
    model: string;
    content_preview: string;
    error_kind: string;
    error: string;
    status_code: number | null;
    retryable: boolean;
    request_id: string;
  }>;
}

export interface TerminalSessionInfo {
  id: string;
  project_root: string;
  shell: string;
  kind: "python" | "shell" | string;
  cwd: string;
  pid: number;
  running: boolean;
  exit_code: number | null;
  created_at: number;
  updated_at: number;
  cursor: number;
  output?: string;
  chunk?: string;
}

export interface SubagentInfo {
  subagent_id: string;
  status: string;
  description?: string;
  task?: string;
  answer?: string;
  error?: string;
  events?: RunEvent[];
  [key: string]: unknown;
}

export interface TestRun {
  id: string;
  label: string;
  command: string[];
  status: string;
  started_at: number;
  finished_at: number;
  exit_code: number | null;
  output: string;
}

export interface ChangeReviewChange {
  path: string;
  kind: string;
  additions: number;
  deletions: number;
  diff?: string;
  checkpointId?: string;
  recoverable?: boolean;
  source?: string;
  note?: string;
  status?: "pending" | "reverted";
}

export type TraceStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

// ── 思维链类型 ──

export type ThoughtStepKind = "thought" | "tool_call";

export interface ThoughtStep {
  id: string;
  kind: ThoughtStepKind;
  title: string;
  status: TraceStatus;
  summary?: string;
  detail?: string;
  startedAt?: number;
  completedAt?: number;
  error?: string;
  // tool_call 专属
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  parentId?: string;
  diffAdded?: number;
  diffRemoved?: number;
}

export interface ThoughtChain {
  id: string;
  steps: ThoughtStep[];
  status: "running" | "completed" | "failed";
  startedAt?: number;
  completedAt?: number;
}

export interface TraceAction {
  id: string;
  stepId: string;
  kind: string;
  title: string;
  status: TraceStatus;
  summary?: string;
  path?: string;
  command?: string;
  additions?: number;
  deletions?: number;
  diffPreview?: string;
  exitCode?: number | null;
  durationMs?: number;
  error?: string;
}

export interface TraceStep {
  id: string;
  title: string;
  status: TraceStatus;
  summary?: string;
  actions: TraceAction[];
}

export interface RunTrace {
  id: string;
  status: TraceStatus;
  phase?: string;
  message?: string;
  thoughtSummary: string;
  assistantDraft: string;
  steps: TraceStep[];
}

export type UiItem =
  | { kind: "user"; id: string; text: string; status?: "pending" | "failed"; error?: string; canRetry?: boolean }
  | { kind: "assistant"; id: string; text: string }
  | {
      kind: "thinking";
      id: string;
      status: "running" | "done" | "error";
      title?: string;
      items: UiItem[];
    }
  | {
      kind: "thought_chain";
      id: string;
      chain: ThoughtChain;
    }
  | {
      kind: "change_review";
      id: string;
      status: "pending" | "confirmed" | "reverted";
      changes: ChangeReviewChange[];
      additions: number;
      deletions: number;
    }
  | {
      kind: "agent_run";
      id: string;
      trace: RunTrace;
    }
  | {
      kind: "tool";
      id: string;
      name: string;
      args: unknown;
      status: "running" | "done" | "error" | "blocked";
      summary?: string;
      output?: string;
      modelSummary?: string;
      error?: string;
      parentId?: string;
      commandKind?: string;
      command?: string;
      jobId?: string;
      exitCode?: number | null;
      durationMs?: number;
      runtime?: string;
      outputPreview?: string;
    }
  | { kind: "notice"; id: string; text: string; level: "info" | "warn" }
  | {
      kind: "approval";
      id: string;
      toolName: string;
      reason: string;
      args: unknown;
      status: "pending" | "approved" | "denied";
    }
  | { kind: "todo"; id: string; progressText: string; todos: unknown[] }
  | { kind: "subagent"; id: string; status: string; parentToolCallId?: string };
