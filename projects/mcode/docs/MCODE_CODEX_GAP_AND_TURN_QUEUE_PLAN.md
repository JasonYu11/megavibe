# Mcode Codex Gap And Turn Queue Plan

## Immediate Product Gaps

Mcode is close to a Codex-style local workbench, but several workflows still need stronger product boundaries:

- Model selection should be visible where the user sends a task, not only hidden in settings.
- Runtime tools should separate Python REPL and shell terminals.
- File preview should offer a direct "open in IDE" action with a configurable target.
- While the agent is running, user input needs explicit semantics: guide, queue, or interrupt.

## Model Selection

The composer should own quick model selection because it is part of task intent. Settings remains the durable project-level source of truth.

Current implementation:

- DeepSeek-V4 Pro
- DeepSeek-V4 Pro with thinking mode
- DeepSeek-V4 Flash
- DeepSeek-V4 Flash with thinking mode

`provider.model` is active for agent calls. `provider.thinking_mode` is stored as first-class project configuration and maps to DeepSeek's OpenAI-compatible request body:

- Disabled: `thinking: { type: "disabled" }`
- Enabled: `thinking: { type: "enabled" }` plus `reasoning_effort: "high"`

Important implementation detail: when thinking mode combines with tool calls, DeepSeek requires `reasoning_content` to be preserved in later requests. Mcode now stores assistant reasoning content on session messages and replays it as `reasoning_content` when present. The full queue/guidance implementation should still audit multi-turn tool-call replay before making thinking mode the default.

## Terminal Model

The terminal panel should treat Python and shell sessions as different terminal kinds:

- Python terminal: default new terminal, starts the configured Python in interactive mode.
- Shell terminal: manually created when the user needs project commands.
- Multiple terminals remain project-scoped and switchable via compact tabs.

This matches how users normally work in agent apps: Python for exploration, shell for build/test/git.

## File Opening

File preview should not become a full editor. Mcode should remain an agent workbench and hand off editing to the user's IDE.

Supported open targets:

- Cursor
- Visual Studio Code
- Finder reveal
- system default
- custom macOS app name

## Running-Turn Conversation Semantics

The current controller allows only one active turn per session. Sending a second message during a run returns a conflict. This is safe but product-hostile.

The correct design is not to directly mutate the active model call. A model request already in flight cannot reliably absorb late user input. Instead, Mcode should support three explicit actions:

1. Guide current run

   The user adds steering information while the agent is running. The backend records a `guidance_added` event. The active agent checks for guidance at safe boundaries: before the next model call, before a tool call, and after a tool result. Guidance is appended as a high-priority user note to the next model call in the same turn.

2. Queue next turn

   The user sends a follow-up to run after the current turn completes. The backend stores it in a per-session queue. After the current turn saves final state, the controller starts the next queued turn automatically, preserving order.

3. Interrupt and replace

   The user explicitly cancels the active turn and starts a new message. This should require a clear UI action because it can leave partial files, pending approvals, or running jobs.

## Backend Design

Add a durable queue file under the project run/session state:

```text
.sessions/<session>.queue.json
```

Queue item shape:

```json
{
  "id": "queued-...",
  "message": "...",
  "mode": "guide" | "queue",
  "created_at": 0,
  "status": "pending" | "consumed" | "cancelled"
}
```

Controller API additions:

- `POST /sessions/{id}/guidance`
- `POST /sessions/{id}/queue`
- `DELETE /sessions/{id}/queue/{queued_id}`
- `GET /sessions/{id}/queue`

Agent integration:

- Add a guidance provider callback to `Agent`.
- Before each model/tool boundary, consume pending guidance and emit `guidance_consumed`.
- On turn completion, ControllerManager drains the queued-turn list one at a time.

## UI Design

When running:

- Composer remains editable.
- Primary button becomes `加入队列`.
- A secondary segmented option switches between `引导当前任务` and `排队下一轮`.
- Stop remains a separate icon button so "send more context" is not confused with cancel.
- Queued messages appear under the activity chips and can be cancelled before execution.

Failure handling:

- If a turn fails, queued follow-ups remain pending.
- If a turn is cancelled, user chooses whether to keep or clear the queue.
- Pending approvals pause queue execution until resolved.

## Acceptance Criteria

- Sending during a run never disappears.
- Queued messages survive page refresh.
- Guidance is consumed only at safe model/tool boundaries.
- Queue execution never overlaps with an active turn.
- Cancel and undo flows remain explicit around file changes.
