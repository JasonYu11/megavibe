from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


NOISY_TRANSCRIPT_EVENTS = {
    "command_output",
    "job_output",
    "checkpoint_saved",
    "preview",
    "compact_check",
    "compact_skipped",
    "test_approval_auto_allowed",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a debug report from Mcode UI run logs.")
    parser.add_argument("root", help="Project root that contains .runs/.sessions")
    parser.add_argument("--session", default="", help="Session id. Defaults to newest .runs event file.")
    parser.add_argument("--out", default="", help="Output report JSON path")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    session_id = args.session or _newest_session_id(root)
    if not session_id:
        raise SystemExit(f"No .runs/*.events.jsonl found under {root}")

    events_path = root / ".runs" / f"{session_id}.events.jsonl"
    summary_path = root / ".runs" / f"{session_id}.summary.json"
    session_path = root / ".sessions" / f"{session_id}.jsonl"
    events = _read_jsonl(events_path)
    messages = _read_jsonl(session_path)
    summary = _read_json(summary_path)

    kinds = Counter(str(event.get("kind", "")) for event in events)
    tool_counts = Counter(
        str(event.get("data", {}).get("name", ""))
        for event in events
        if event.get("kind") == "tool_dispatch"
    )
    command_output_chars = sum(
        len(str(event.get("data", {}).get("text", "")))
        for event in events
        if event.get("kind") == "command_output"
    )
    ui_turn_answer_notices = [
        event
        for event in events
        if event.get("kind") == "notice"
        and str(event.get("data", {}).get("message", "")).startswith("UI turn answer:")
    ]
    transcript_noise = [
        event
        for event in events
        if str(event.get("kind", "")) in NOISY_TRANSCRIPT_EVENTS
    ]
    final_assistant_messages = [
        msg.get("content", "")
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("content")
    ]

    report = {
        "root": str(root),
        "session_id": session_id,
        "events_path": str(events_path),
        "summary_path": str(summary_path),
        "session_path": str(session_path),
        "event_count": len(events),
        "message_count": len(messages),
        "event_kind_counts": dict(kinds.most_common()),
        "tool_counts": dict(tool_counts.most_common()),
        "command_output_event_count": kinds.get("command_output", 0),
        "command_output_chars": command_output_chars,
        "transcript_noise_event_count": len(transcript_noise),
        "ui_turn_answer_notice_count": len(ui_turn_answer_notices),
        "summary_status": summary.get("status"),
        "summary_final_answer": summary.get("final_answer", ""),
        "last_assistant_message": final_assistant_messages[-1] if final_assistant_messages else "",
        "warnings": _warnings(kinds, command_output_chars, ui_turn_answer_notices, final_assistant_messages, summary),
    }
    out_path = Path(args.out).expanduser().resolve() if args.out else root / f"{session_id}.ui-debug-report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[ui-debug-report] wrote {out_path}")
    return 0


def _warnings(
    kinds: Counter,
    command_output_chars: int,
    ui_turn_answer_notices: list[dict[str, Any]],
    final_assistant_messages: list[str],
    summary: dict[str, Any],
) -> list[str]:
    rows: list[str] = []
    if ui_turn_answer_notices:
        rows.append("UI turn answer notice leaked into event stream")
    if kinds.get("command_output", 0) > 5 or command_output_chars > 4000:
        rows.append("command_output is noisy; UI should compact command output events")
    if summary.get("status") == "completed" and not final_assistant_messages:
        rows.append("turn completed but no final assistant message was saved in session")
    if summary.get("final_answer") and final_assistant_messages:
        if str(summary.get("final_answer", "")).strip() not in final_assistant_messages[-1]:
            rows.append("summary final_answer differs from last saved assistant message")
    return rows


def _newest_session_id(root: Path) -> str:
    run_dir = root / ".runs"
    if not run_dir.exists():
        return ""
    paths = sorted(run_dir.glob("*.events.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[0].name.removesuffix(".events.jsonl") if paths else ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"kind": "invalid_jsonl", "raw": line})
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid_json"}


if __name__ == "__main__":
    raise SystemExit(main())
