from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.control import MiniController
from mini_agent_lab.session_store import SessionStore


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  OK: {message}")


class SlowController(MiniController):
    def _run_turn(self, message: str, plan: bool) -> None:
        time.sleep(0.15)


def test_session_store_atomic_save(tmp: Path) -> None:
    store = SessionStore(tmp / ".sessions")
    session = Session("system")
    session.add("user", "hello")
    path = store.save("demo", session)
    check(path.exists(), "atomic save creates session file")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    check(rows[-1]["content"] == "hello", "atomic save preserves session messages")
    check(not list((tmp / ".sessions").glob("*.tmp")), "atomic save leaves no temp files")
    loaded = store.load("demo")
    check(loaded.messages[-1].content == "hello", "atomic saved session can be loaded")


def test_controller_running_guard_and_cancel(tmp: Path) -> None:
    controller = SlowController(root=tmp, session_id="demo", system_prompt="system")
    snapshot = controller.snapshot()
    check(snapshot.root == str(tmp), "controller snapshot returns project root")
    check(snapshot.session_id == "demo", "controller snapshot returns session id")
    result = controller.submit("first")
    check(result["status"] == "started", "controller starts first turn")
    try:
        controller.submit("second")
    except RuntimeError as exc:
        check("active turn" in str(exc), "controller rejects concurrent turn")
    else:
        raise AssertionError("controller accepted concurrent turn")
    cancel = controller.cancel()
    check(cancel["status"] == "cancel_requested", "controller records cancel request")
    while controller.snapshot().running:
        time.sleep(0.02)
    check(not controller.snapshot().running, "controller clears running state after turn")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_session_store_atomic_save(root)
        test_controller_running_guard_and_cancel(root)
    print("All controller tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
