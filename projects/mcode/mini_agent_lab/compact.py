from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from mini_agent_lab.agent.session import Session
from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.provider import Message


@dataclass(frozen=True)
class CompactResult:
    changed: bool
    summary: str = ""
    archive_path: str = ""
    original_messages: int = 0
    kept_messages: int = 0


def session_chars(session: Session) -> int:
    total = 0
    for message in session.messages:
        total += len(message.role) + len(message.content or "")
        if message.name:
            total += len(message.name)
        if message.tool_call_id:
            total += len(message.tool_call_id)
        if message.tool_calls:
            for call in message.tool_calls:
                total += len(call.id) + len(call.name) + len(json.dumps(call.arguments, ensure_ascii=False))
    return total


def should_compact(session: Session, trigger_chars: int) -> bool:
    return session_chars(session) >= trigger_chars


def compact_session(
    session: Session,
    recent_keep: int = 12,
    archive_dir: Union[str, Path] = ".archives",
    force: bool = False,
    provider=None,
    context_config: Optional[ContextConfig] = None,
) -> CompactResult:
    messages = session.messages
    if len(messages) <= recent_keep + 2 and not force:
        return CompactResult(changed=False, original_messages=len(messages), kept_messages=len(messages))

    head_count = 1 if messages and messages[0].role == "system" else 0
    tail_start = max(head_count, len(messages) - recent_keep)
    while tail_start > head_count and messages[tail_start].role == "tool":
        tail_start -= 1

    region = messages[head_count:tail_start]
    if not region:
        return CompactResult(changed=False, original_messages=len(messages), kept_messages=len(messages))

    summary = summarize_for_compact(region, provider=provider, context_config=context_config)
    archive_path = archive_messages(region, archive_dir)

    compacted = []
    compacted.extend(messages[:head_count])
    compacted.append(
        Message(
            role="user",
            content="Summary of earlier conversation compacted to save context:\n\n" + summary,
        )
    )
    compacted.extend(messages[tail_start:])
    session.messages = compacted

    return CompactResult(
        changed=True,
        summary=summary,
        archive_path=str(archive_path),
        original_messages=len(messages),
        kept_messages=len(session.messages),
    )


def summarize_for_compact(
    messages: list[Message],
    provider=None,
    context_config: Optional[ContextConfig] = None,
) -> str:
    cfg = context_config or ContextConfig()
    mode = (cfg.summary_mode or "llm").lower()
    if mode == "local":
        return summarize_messages(messages)
    if provider is None:
        raise RuntimeError("LLM compact requires a provider; set summary_mode='local' for offline compact")
    return summarize_messages_with_llm(messages, provider=provider, context_config=cfg)


def summarize_messages_with_llm(
    messages: list[Message],
    provider,
    context_config: ContextConfig,
) -> str:
    transcript = render_transcript(messages)
    target_tokens = _target_summary_tokens(transcript, context_config)
    prompt = f"""You are compacting the earlier part of a coding agent conversation.
The original messages will be archived and replaced by your summary, so the agent must be able to continue the task from the summary alone.

Write a dense, factual summary using these exact headings, in this exact order:

## Goal
User intent, explicit requirements, constraints, and preferences.

## Decisions
Important choices already made and why.

## Files Read
Files inspected and the concrete facts learned from them.

## Files Modified
Files created or edited, exact changes, and checkpoint ids if present.

## Commands & Results
Shell/background commands, tests, downloads, and their relevant outcomes.

## Errors & Fixes
Failures encountered and how they were resolved.

## Pending / Next Step
What remains to do and the most useful next action.

Rules:
- Preserve file paths, symbols, commands, ids, numbers, and exact facts.
- Do not invent facts.
- Only summarize facts present in the transcript. If a heading has no facts, write "- None".
- Prefer concise bullets.
- Target about {target_tokens} tokens. Do not over-compress; retain enough detail for a coding agent to resume safely.
- Your visible final answer must contain the summary. Do not leave the final answer empty.
"""
    summary_messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=transcript),
    ]
    response = provider.complete(summary_messages, max_tokens=_summary_output_budget(target_tokens, context_config))
    summary = (response.content or "").strip()
    if not summary:
        retry_prompt = prompt + "\n\nThe previous attempt produced an empty visible answer. Now output the compact summary in the visible final answer."
        response = provider.complete(
            [
                Message(role="system", content=retry_prompt),
                Message(role="user", content=transcript),
            ],
            max_tokens=_summary_output_budget(target_tokens * 2, context_config),
        )
        summary = (response.content or "").strip()
    if summary and not _has_required_headings(summary):
        retry_prompt = prompt + "\n\nThe previous attempt did not follow the required heading structure. Rewrite the compact summary with every exact heading, even if a section is '- None'."
        response = provider.complete(
            [
                Message(role="system", content=retry_prompt),
                Message(role="user", content=transcript),
            ],
            max_tokens=_summary_output_budget(target_tokens * 2, context_config),
        )
        retry_summary = (response.content or "").strip()
        if retry_summary:
            summary = retry_summary
    if not summary:
        raise RuntimeError("LLM compact returned an empty summary")
    return summary


def render_transcript(messages: list[Message]) -> str:
    parts = []
    for message in messages:
        if message.role == "user":
            parts.append(f"[user]\n{message.content}")
        elif message.role == "assistant":
            if message.content:
                parts.append(f"[assistant]\n{message.content}")
            for call in message.tool_calls or []:
                parts.append(
                    "[assistant tool_call]\n"
                    + json.dumps(call.to_dict(), ensure_ascii=False, indent=2)
                )
        elif message.role == "tool":
            header = f"[tool result name={message.name} id={message.tool_call_id}]"
            parts.append(f"{header}\n{message.content}")
        elif message.role == "system":
            parts.append(f"[system]\n{message.content}")
    return "\n\n".join(parts)


def _target_summary_tokens(transcript: str, cfg: ContextConfig) -> int:
    estimated_tokens = max(1, len(transcript) // max(1, cfg.chars_per_token))
    target = int(estimated_tokens * cfg.target_summary_ratio)
    target = max(cfg.min_summary_tokens, target)
    target = min(cfg.max_summary_tokens, target)
    return max(1, target)


def _summary_output_budget(target_tokens: int, cfg: ContextConfig) -> int:
    # DeepSeek reasoning models may spend output budget on reasoning_content
    # before producing visible content. Give the summarizer headroom while still
    # bounding the call.
    budget = max(target_tokens + 1000, target_tokens * 2)
    return min(max(cfg.max_summary_tokens * 2, cfg.min_summary_tokens), budget)


def _has_required_headings(summary: str) -> bool:
    required = [
        "## Goal",
        "## Decisions",
        "## Files Read",
        "## Files Modified",
        "## Commands & Results",
        "## Errors & Fixes",
        "## Pending / Next Step",
    ]
    return all(heading in summary for heading in required)


def summarize_messages(messages: list[Message]) -> str:
    user_requests = []
    tools = []
    files_read = []
    files_written = []
    bash_commands = []
    assistant_notes = []

    for message in messages:
        if message.role == "user" and message.content:
            user_requests.append(_one_line(message.content))
        elif message.role == "assistant":
            if message.content:
                assistant_notes.append(_one_line(message.content))
            for call in message.tool_calls or []:
                tools.append(call.name)
                path = call.arguments.get("path")
                if call.name == "read_file" and path:
                    files_read.append(str(path))
                if call.name in {"write_file", "edit_file"} and path:
                    files_written.append(str(path))
                if call.name == "bash":
                    cmd = call.arguments.get("command")
                    if cmd:
                        bash_commands.append(_one_line(str(cmd)))
        elif message.role == "tool":
            if message.name:
                tools.append(message.name)

    lines = ["## Compact Summary"]
    _append_section(lines, "User Requests", user_requests[-8:])
    _append_section(lines, "Tools Used", _unique(tools)[-20:])
    _append_section(lines, "Files Read", _unique(files_read)[-20:])
    _append_section(lines, "Files Written", _unique(files_written)[-20:])
    _append_section(lines, "Bash Commands", bash_commands[-10:])
    _append_section(lines, "Assistant Notes", assistant_notes[-8:])
    return "\n".join(lines).strip()


def archive_messages(messages: list[Message], archive_dir: Union[str, Path]) -> Path:
    directory = Path(archive_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}.jsonl")
    with path.open("w", encoding="utf-8") as f:
        for message in messages:
            f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
    return path


def _append_section(lines: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    lines.append("")
    lines.append(f"### {title}")
    for item in items:
        lines.append(f"- {item}")


def _one_line(text: str, limit: int = 220) -> str:
    text = " ".join(text.strip().split())
    return text if len(text) <= limit else text[:limit] + "..."


def _unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
