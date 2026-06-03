from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.compact import compact_session, session_chars
from mini_agent_lab.config import load_config
from mini_agent_lab.provider import DeepSeekProvider
from mini_agent_lab.session_store import SessionStore


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/compact_demo.py <session-id> [--force]")
        return 2
    session_id = sys.argv[1]
    force = "--force" in sys.argv[2:]
    recent_keep = None
    if "--recent-keep" in sys.argv:
        idx = sys.argv.index("--recent-keep")
        recent_keep = int(sys.argv[idx + 1])
    app_cfg = load_app_config()
    provider = None
    if app_cfg.context.summary_mode.lower() == "llm":
        cfg = load_config()
        provider = DeepSeekProvider(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=cfg.model,
            temperature=cfg.temperature,
        )
    store = SessionStore(app_cfg.paths.session_dir)
    session = store.load(session_id)
    before = session_chars(session)
    result = compact_session(
        session,
        recent_keep=recent_keep if recent_keep is not None else app_cfg.context.recent_keep,
        archive_dir=app_cfg.paths.archive_dir,
        force=force,
        provider=provider,
        context_config=app_cfg.context,
    )
    after = session_chars(session)
    if result.changed:
        store.save(session_id, session)
        print(f"compacted {session_id}")
        print(f"messages: {result.original_messages} -> {result.kept_messages}")
        print(f"chars: {before} -> {after}")
        print(f"archive: {result.archive_path}")
        print("\nsummary:\n" + result.summary)
    else:
        print(f"nothing to compact for {session_id}")
        print(f"chars={before}, trigger_chars={app_cfg.context.trigger_chars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
