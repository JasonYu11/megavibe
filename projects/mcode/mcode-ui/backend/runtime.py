from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from approvals import ApprovalStore
from event_broker import event_broker
from project_store import Project, project_root


def _runtime_root() -> Path:
    configured = os.environ.get("MCODE_RUNTIME_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    backend_root = Path(__file__).resolve().parent
    for candidate in (backend_root.parents[1], backend_root.parent):
        if (candidate / "mini_agent_lab").exists() and (candidate / "scripts").exists():
            return candidate
    return backend_root.parents[1]


REPO_ROOT = _runtime_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agent_chat import SYSTEM_PROMPT
from settings_api import prime_settings_env
from mini_agent_lab.control import ControllerManager
from mini_agent_lab.events import Event
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.safety import Approver


class UiApprover(Approver):
    def __init__(self, approvals: ApprovalStore, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.approvals = approvals

    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        session_id = str(getattr(self.sink, "session_id", ""))
        approval = self.approvals.create(
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
        )
        self.sink.emit(
            Event(
                "safety_ask",
                {
                    "approval_id": approval.id,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "reason": reason,
                },
            )
        )
        allowed = self.approvals.wait(approval.id)
        if not allowed:
            self.sink.emit(Event("safety_deny", {"tool_name": tool_name, "reason": "user denied or approval expired"}))
        return allowed


class AgentRuntime:
    """Thin HTTP runtime facade over session-scoped controllers."""

    def __init__(self) -> None:
        self.approvals = ApprovalStore()
        self.controllers = ControllerManager(
            system_prompt=SYSTEM_PROMPT,
            approver_factory=lambda sink: UiApprover(self.approvals, sink=sink),
            env_loader=self._prime_env,
            recorder_factory=self._recorder,
        )

    def start_turn(
        self,
        project: Project,
        session_id: str,
        message: str,
        plan: bool = False,
        permission_mode: str = "auto_review",
        attachment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.controllers.submit(
            project_root(project),
            session_id,
            message,
            plan=plan,
            permission_mode=permission_mode,
            attachment_ids=attachment_ids or [],
        )

    def cancel_turn(self, project: Project, session_id: str) -> dict[str, Any]:
        return self.controllers.cancel(project_root(project), session_id)

    def controller_snapshot(self, project: Project, session_id: str) -> dict[str, Any]:
        snapshot = self.controllers.snapshot(project_root(project), session_id)
        return {
            "session_id": snapshot.session_id,
            "root": snapshot.root,
            "running": snapshot.running,
            "cancel_requested": snapshot.cancel_requested,
            "started_at": snapshot.started_at,
            "updated_at": snapshot.updated_at,
        }

    def create_session(self, project: Project, label: str = "ui") -> dict[str, Any]:
        return self.controllers.new_session(project_root(project), label=label)

    def list_approvals(self, session_id: str = "") -> list[dict[str, Any]]:
        return self.approvals.list(session_id=session_id)

    def decide_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        item = self.approvals.decide(approval_id, approved)
        return {
            "id": item.id,
            "status": item.status,
            "approved": item.approved,
        }

    @staticmethod
    def _prime_env(root: Path) -> None:
        prime_settings_env(root)

    @staticmethod
    def _recorder(run_dir: Path, run_id: str, session_id: str) -> RunRecorder:
        root = run_dir.parent
        return RunRecorder(
            directory=run_dir,
            run_id=run_id,
            session_id=session_id,
            record_downstream=lambda record: event_broker.publish(root, session_id, record),
        )
