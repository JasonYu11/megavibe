from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class EventSink:
    def emit(self, event: Event) -> None:
        raise NotImplementedError


class NullSink(EventSink):
    def emit(self, event: Event) -> None:
        return


class PrintSink(EventSink):
    def emit(self, event: Event) -> None:
        kind = event.kind
        data = event.data
        if kind in {"turn_started", "assistant_message", "turn_completed", "turn_paused"}:
            return
        if kind == "tool_dispatch":
            if data["name"] == "todo_write":
                return
            prefix = f"[subagent:{data['subagent_id']}] " if data.get("subagent_id") else ""
            print(f"{prefix}[tool] {data['name']}({data.get('arguments_json', '{}')})")
            return
        if kind == "tool_result":
            if data.get("name") == "todo_write":
                return
            if data.get("name") == "bash":
                return
            if data.get("subagent_id"):
                print(f"[subagent:{data['subagent_id']}]")
            print(data.get("result", ""))
            print()
            return
        if kind == "subagent_started":
            print(
                f"[subagent] started {data.get('subagent_id')} "
                f"tools={data.get('tools')} max_steps={data.get('max_steps')}"
            )
            return
        if kind == "subagent_completed":
            print(f"[subagent] completed {data.get('subagent_id')}")
            return
        if kind == "subagent_failed":
            print(f"[subagent] failed {data.get('subagent_id')}: {data.get('error')}")
            return
        if kind == "subagent_cancel_requested":
            print(f"[subagent] cancel requested {data.get('subagent_id')}")
            return
        if kind == "subagent_cancelled":
            print(f"[subagent] cancelled {data.get('subagent_id')}")
            return
        if kind == "todo_updated":
            print(f"[todo] {data.get('progress_text', str(data['completed']) + '/' + str(data['total']) + ' done')}")
            for item in data.get("todos", []):
                indent = "    " if item.get("level") == 1 else "  "
                label = item.get("content", "")
                status = item.get("status", "pending")
                if status == "completed":
                    marker = "[x]"
                elif status == "in_progress":
                    marker = ">"
                    label = item.get("activeForm") or label
                else:
                    marker = "[ ]"
                print(f"{indent}{marker} {label}")
            if data.get("done"):
                print("  all todos completed")
            print()
            return
        if kind == "plan_blocked":
            print(f"[plan] blocked writer tool in plan mode: {data['tool_name']}")
            return
        if kind == "plan_seeded":
            print(f"[plan] seeded todo list from approved plan")
            return
        if kind == "safety_ask":
            print(f"[safety] {data['tool_name']} requires approval: {data['reason']}")
            print(f"[safety] arguments: {data['arguments']}")
            return
        if kind == "safety_deny":
            print(f"[safety] denied {data['tool_name']}: {data['reason']}")
            return
        if kind == "preview":
            print(f"[preview] {data['kind']} {data['path']}")
            print((data.get("diff") or "(no diff)").rstrip())
            return
        if kind == "checkpoint_saved":
            print(f"[checkpoint] saved {data['id']} for {data['path']}")
            return
        if kind == "git_baseline_captured":
            if data.get("is_repo"):
                print(
                    f"[git] baseline branch={data.get('branch')} "
                    f"head={data.get('head')} dirty={data.get('dirty_count')}"
                )
            else:
                print(f"[git] no repo baseline ({data.get('error', 'not a git repository')})")
            return
        if kind == "git_baseline_failed":
            print(f"[git] baseline failed: {data.get('error')}")
            return
        if kind == "git_classify_failed":
            print(f"[git] classify failed: {data.get('error')}")
            return
        if kind == "git_baseline_missing":
            print(f"[git] baseline missing for write: {data.get('path')}")
            return
        if kind == "git_overlap_risk":
            print(
                f"[git] overlap risk {data.get('path')} "
                f"baseline={data.get('status_at_baseline')}"
            )
            return
        if kind == "git_commit_started":
            print(f"[git] commit started files={data.get('files')} message={data.get('message')!r}")
            return
        if kind == "git_commit_done":
            print(f"[git] commit done head={data.get('head')} files={data.get('files')}")
            return
        if kind == "git_commit_failed":
            print(f"[git] commit failed: {data.get('error')}")
            return
        if kind == "command_started":
            print(f"[command] started pid={data.get('pid')} timeout={data.get('timeout_seconds')}s")
            return
        if kind == "command_output":
            print(str(data.get("text", "")).rstrip())
            return
        if kind == "command_finished":
            print(
                f"[command] finished exit={data.get('exit_code')} "
                f"duration_ms={data.get('duration_ms')} timed_out={data.get('timed_out')}"
            )
            return
        if kind == "job_started":
            print(f"[job] started {data.get('job_id')} pid={data.get('pid')} log={data.get('log_path')}")
            return
        if kind == "job_output":
            print(f"[job:{data.get('job_id')}] {str(data.get('text', '')).rstrip()}")
            return
        if kind == "job_finished":
            print(
                f"[job] finished {data.get('job_id')} status={data.get('status')} "
                f"exit={data.get('exit_code')} duration_ms={data.get('duration_ms')}"
            )
            return
        if kind in {"compact_check", "compact_skipped"}:
            return
        if kind == "compact_started":
            print(
                f"[compact] started chars={data['chars']} "
                f"trigger={data['trigger_chars']} mode={data['summary_mode']}"
            )
            return
        if kind == "compact_done":
            print(
                f"[compact] archived {data['archived_messages']} message(s) "
                f"to {data['archive_path']}; kept {data['kept_messages']}; "
                f"chars {data['before_chars']} -> {data['after_chars']}"
            )
            return
        if kind == "compact_failed":
            print(f"[compact] failed: {data['error']}")
            return
        if kind == "notice":
            print(f"[notice] {data.get('message', '')}")
            return
        print(f"[event:{kind}] {data}")
