# Mcode Event Stream

This document is the stable UI/debug contract for `.runs/*.events.jsonl` and
`.runs/*.summary.json`.

The design follows the Reasonix pattern:

- The model still receives plain tool output strings.
- The UI and logs receive structured events.
- `.events.jsonl` is the append-only timeline.
- `.summary.json` is the compact latest-state snapshot.

## Event Record Shape

Every persisted event line is JSON:

```json
{
  "seq": 1,
  "time": 1780320000.0,
  "time_text": "2026-06-01 21:30:00",
  "kind": "tool_result",
  "data": {}
}
```

Common fields:

- `seq`: monotonic sequence number inside one run.
- `time`: Unix timestamp.
- `time_text`: local readable time.
- `kind`: event type.
- `data`: event payload.

Consumers should treat unknown `kind` values as informational rows and keep
rendering the rest of the stream.

## Turn Events

### `turn_started`

Start of one user turn.

```json
{"input": "create a file"}
```

UI use: start spinner, show user input, clear final answer.

### `assistant_message`

One model response. It may contain final text or tool calls.

```json
{
  "content": "",
  "tool_calls": [
    {"id": "call-1", "name": "write_file", "arguments": {"path": "a.txt"}}
  ]
}
```

UI use: show pending tool cards or assistant text.

### `turn_completed`

The turn ended with a final answer.

```json
{"answer": "done"}
```

### `turn_paused`

The turn hit `max_steps`.

```json
{"message": "paused after 300 tool-call round(s)", "max_steps": 300}
```

UI use: show resumable paused state.

## Tool Events

### `tool_dispatch`

The model requested a tool.

```json
{
  "name": "read_file",
  "arguments": {"path": "README.md"},
  "arguments_json": "{\"path\":\"README.md\"}"
}
```

UI use: create a running tool card.

### `tool_result`

The tool completed, failed, or was blocked.

```json
{
  "name": "read_file",
  "result": "1| hello",
  "output": "1| hello",
  "ok": true,
  "error": "",
  "error_kind": "",
  "blocked": false,
  "truncated": false
}
```

Fields:

- `result`: legacy alias for `output`.
- `output`: exact string fed back to the model.
- `ok`: true when the call succeeded.
- `error`: concise failure reason for UI.
- `error_kind`: one of `unknown_tool`, `invalid_args`, `tool_error`,
  `blocked`, `safety_deny`, or empty on success.
- `blocked`: true when policy, plan mode, approval, or git overlap stopped it.
- `truncated`: true when `output` was shortened before being fed to the model.

UI use: mark card done/error/blocked, display output on expand, show
truncation badge.

### `notice`

Out-of-band user-visible information.

```json
{"message": "tool output truncated: 500 of 12500 characters omitted"}
```

Examples: tool loop guard, truncation, model step count.

## Todo Events

### `todo_updated`

Current task plan state.

```json
{
  "completed": 1,
  "total": 3,
  "pending": 1,
  "in_progress": 1,
  "progress_text": "1/3 done",
  "done": false,
  "current": {"content": "Implement"},
  "todos": []
}
```

UI use: render todo panel and progress status.

## File Preview And Checkpoints

### `preview`

A write-capable tool has a previewable file change.

```json
{"kind": "write", "path": "notes/a.md", "diff": "--- before\n+++ after\n"}
```

UI use: show simple diff preview.

### `checkpoint_saved`

A checkpoint was created before a file-changing tool ran.

```json
{"id": "20260601-213000-001", "path": "notes/a.md"}
```

UI use: expose rewind/restore affordance.

## Git Events

### `git_baseline_captured`

Baseline captured at turn start.

```json
{
  "path": ".gitstate/run.baseline.json",
  "is_repo": true,
  "root": "/workspace",
  "branch": "main",
  "head": "abc123",
  "dirty_count": 0,
  "error": ""
}
```

### `git_changes_classified`

Final comparison between baseline and current git state.

```json
{
  "current_dirty": 2,
  "user_existing": ["user.txt"],
  "agent_created": ["new.txt"],
  "agent_modified": ["agent.py"],
  "overlap": ["user.txt"],
  "resolved_baseline_dirty": []
}
```

UI use: changed-files panel and risk banner.

### `git_overlap_risk`

A write targets a file that was dirty before the agent turn.

```json
{
  "path": "user.txt",
  "target": "/workspace/user.txt",
  "status_at_baseline": " M user.txt",
  "tool_name": "write_file",
  "reason": "..."
}
```

UI use: ask user before write; keep risk auditable even if approved.

### `git_commit_started`, `git_commit_done`, `git_commit_failed`

Controlled local commit lifecycle.

```json
{"files": ["agent.py"], "message": "test: update", "risk": {}}
```

`done` adds `head` and `branch`; `failed` adds `error`.

## Shell And Background Job Events

### `command_started`, `command_output`, `command_finished`

Foreground command lifecycle.

```json
{"command_id": "cmd-1", "command": "python tests.py", "pid": 123, "timeout_seconds": 30}
```

`command_output` streams text chunks. `command_finished` records
`exit_code`, `duration_ms`, and `timed_out`.

### `job_started`, `job_output`, `job_finished`

Background job lifecycle. Jobs include `job_id`, `pid`, `log_path`, and final
status.

## Compaction Events

### `compact_check`, `compact_skipped`

Internal context-window bookkeeping. UI may ignore.

### `compact_started`

Auto or manual context compaction began.

```json
{
  "chars": 450000,
  "trigger_chars": 450000,
  "recent_keep": 12,
  "summary_mode": "llm"
}
```

### `compact_done`

Compaction completed.

```json
{
  "archive_path": ".archives/session.jsonl",
  "archived_messages": 40,
  "original_messages": 55,
  "kept_messages": 12,
  "before_chars": 460000,
  "after_chars": 90000,
  "summary_chars": 12000
}
```

### `compact_failed`

Compaction failed but the run can continue.

```json
{"error": "provider error", "chars": 460000}
```

## Safety And Plan Events

### `safety_ask`

Permission approval requested.

```json
{"tool_name": "bash", "arguments": {"command": "git commit"}, "reason": "..."}
```

### `safety_deny`

Policy denied the call without asking.

```json
{"tool_name": "bash", "arguments": {}, "reason": "..."}
```

### `plan_blocked`

Plan mode blocked a write-capable tool.

```json
{"tool_name": "write_file", "arguments": {"path": "a.txt"}}
```

## Summary Snapshot

`.summary.json` is the latest state for status bars and dashboards. Important
fields:

- `status`: `created`, `running`, `tool_running`, `waiting_approval`,
  `command_running`, `job_running`, `compacting`, `completed`, or `paused`.
- `current_input`: current user request preview.
- `current_tool`: running tool name and compact args.
- `current_command`: running foreground command.
- `last_tool_result`: structured result from the latest tool.
- `todo`: current todo progress.
- `git`: baseline, classification, overlap risks, and commit state.
- `jobs`: background job map.
- `last_notice`: latest informational notice.
- `last_error`: latest error/risk.
- `final_answer`: final answer preview after completion.
- `recent_events`: compact event tail.

## Debug Tools

Render a readable event timeline:

```bash
python scripts/run_replay.py .runs/example.events.jsonl
```

Render the latest run if no path is provided:

```bash
python scripts/run_replay.py
```

Render a status snapshot:

```bash
python scripts/run_status.py .runs/example.summary.json
```
