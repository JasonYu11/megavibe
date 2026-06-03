from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.attachments import AttachmentStore, attachment_context
from mini_agent_lab.config import load_config
from mini_agent_lab.events import Event, EventSink
from mini_agent_lab.memory import AutoMemoryStore, compose_system_prompt, load_memory
from mini_agent_lab.provider import DeepSeekProvider, ProviderError
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.runtime_env import discover_runtime, runtime_to_dict
from mini_agent_lab.auto_review import AutoReviewAgent, AutoReviewConfig
from mini_agent_lab.safety import Approver, PermissionMode, SafetyGate
from mini_agent_lab.session_store import SessionStore
from mini_agent_lab.skill import Skill, SkillStore, apply_skill_index, render_skill
from mini_agent_lab.subagent_manager import SubagentManager
from mini_agent_lab.tool import default_registry
from mini_agent_lab.tool.registry import ToolRegistry


ApproverFactory = Callable[[EventSink], Approver]
EnvLoader = Callable[[Path], None]
RecorderFactory = Callable[[Path, str, str], RunRecorder]

_cwd_lock = threading.Lock()


@dataclass(frozen=True)
class ControllerSnapshot:
    session_id: str
    root: str
    running: bool
    cancel_requested: bool
    started_at: float
    updated_at: float


class MiniController:
    """Run coordinator for one session.

    The Agent still owns the model-tool loop. This controller owns lifecycle:
    submit/cancel/snapshot/history and the one-turn-at-a-time guard.
    """

    def __init__(
        self,
        root: str | Path,
        session_id: str,
        system_prompt: str,
        approver_factory: Optional[ApproverFactory] = None,
        env_loader: Optional[EnvLoader] = None,
        recorder_factory: Optional[RecorderFactory] = None,
    ) -> None:
        self.root = Path(root)
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.approver_factory = approver_factory or (lambda sink: Approver(sink=sink))
        self.env_loader = env_loader or (lambda root: None)
        self.recorder_factory = recorder_factory
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._cancel_event = threading.Event()
        self._session: Optional[Session] = None
        self._started_at = 0.0
        self._updated_at = time.time()

    def submit(
        self,
        message: str,
        plan: bool = False,
        permission_mode: PermissionMode = "auto_review",
        attachment_ids: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message is required")
        with self._lock:
            if self._running:
                raise RuntimeError("session already has an active turn")
            self._running = True
            self._cancel_event.clear()
            self._started_at = time.time()
            self._updated_at = self._started_at
            self._thread = threading.Thread(
                target=self._run_guarded,
                args=(message, plan, permission_mode, list(attachment_ids or [])),
                daemon=True,
            )
            self._thread.start()
        return {"status": "started", "session_id": self.session_id}

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            running = self._running
            self._cancel_event.set()
            self._updated_at = time.time()
        self._emit_lifecycle_event("turn_cancel_requested", {"session_id": self.session_id, "running": running})
        return {"status": "cancel_requested" if running else "not_running", "session_id": self.session_id}

    def snapshot(self) -> ControllerSnapshot:
        with self._lock:
            return ControllerSnapshot(
                session_id=self.session_id,
                root=str(self.root),
                running=self._running,
                cancel_requested=self._cancel_event.is_set(),
                started_at=self._started_at,
                updated_at=self._updated_at,
            )

    def resume(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise RuntimeError("cannot resume while session is running")
            self.session_id = session_id
            self._session = None
            self._cancel_event.clear()
            self._updated_at = time.time()
        return {"status": "resumed", "session_id": session_id}

    def new_session(self, label: str = "session") -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise RuntimeError("cannot create a new session while running")
            with _cwd_lock:
                with _pushd(self.root):
                    store = self._session_store()
                    session = self._new_session_object()
                    self.session_id = store.new_id(label)
                    self._session = session
                    store.save(self.session_id, session)
                    self._cancel_event.clear()
                    self._updated_at = time.time()
        return {"id": self.session_id}

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            session = self._session
        if session is None:
            with _cwd_lock:
                with _pushd(self.root):
                    session = self._load_or_create_session()
        return [message.to_dict() for message in session.messages]

    def _run_guarded(self, message: str, plan: bool, permission_mode: PermissionMode, attachment_ids: list[str]) -> None:
        try:
            with _cwd_lock:
                with _pushd(self.root):
                    self._emit_controller_started()
                    self._run_turn(message, plan, permission_mode, attachment_ids)
        except Exception as exc:
            self._record_crash(exc)
        finally:
            with self._lock:
                self._running = False
                self._updated_at = time.time()

    def _run_turn(self, message: str, plan: bool, permission_mode: PermissionMode, attachment_ids: list[str]) -> None:
        agent, store, session, sink = self._build_agent(permission_mode=permission_mode)
        if attachment_ids:
            store_for_attachments = AttachmentStore(self.root / ".attachments")
            metas = [store_for_attachments.get(self.session_id, attachment_id) for attachment_id in attachment_ids]
            message = message + "\n" + attachment_context(metas)
        agent.set_plan_mode(plan)
        try:
            agent.run(message)
        finally:
            store.save(self.session_id, session)

    def _build_agent(self, permission_mode: PermissionMode = "auto_review") -> tuple[Agent, SessionStore, Session, RunRecorder]:
        self.env_loader(self.root)
        app_cfg = load_app_config(self.root / "mcode-config.json")
        runtime_selection = discover_runtime(self.root, app_cfg)
        cfg = load_config()
        provider_cfg = app_cfg.provider
        agent_max_steps = app_cfg.agent.max_steps or cfg.max_steps
        store = SessionStore(self.root / app_cfg.paths.session_dir)
        memory_store = AutoMemoryStore(self.root / app_cfg.paths.memory_dir)
        skill_store = SkillStore(project_root=self.root, custom_paths=list(app_cfg.paths.skill_custom_dirs))
        provider = DeepSeekProvider(
            api_key=cfg.api_key,
            base_url=provider_cfg.base_url or cfg.base_url,
            model=provider_cfg.model or cfg.model,
            temperature=provider_cfg.temperature,
            thinking_mode=provider_cfg.thinking_mode,
            timeout_seconds=provider_cfg.timeout_seconds,
            max_retries=provider_cfg.max_retries,
            proxy_url=provider_cfg.proxy_url,
            trust_env=provider_cfg.trust_env,
        )
        session = self._load_or_create_session(store=store, memory_store=memory_store, skill_store=skill_store)
        sink = self._run_recorder(self.root / app_cfg.paths.run_dir)
        git_baseline_path = self.root / app_cfg.paths.gitstate_dir / f"{self.session_id}.baseline.json"
        registry: ToolRegistry | None = None
        safety_gate = SafetyGate(permission_mode=permission_mode)
        if permission_mode == "auto_review":
            ar_config = AutoReviewConfig.from_dict(safety_gate.policy.raw.get("auto_review"))
            safety_gate.auto_review_agent = AutoReviewAgent(provider, config=ar_config)
        approver = self.approver_factory(sink)

        def run_skill_subagent(skill: Skill, task: str, parent_tool_call_id: str = "") -> str:
            result = subagents.run_task(
                {
                    "prompt": task,
                    "description": f"skill-{skill.name}",
                    "tools": skill.allowed_tools,
                    "max_steps": 0,
                    "run_in_background": False,
                    "_tool_call_id": parent_tool_call_id,
                },
                system_prompt=render_skill(skill),
            )
            return str(result.get("answer") or result)

        def run_task_subagent(arguments: dict) -> dict:
            return subagents.run_task(arguments)

        subagents = SubagentManager(
            root_dir=self.root / app_cfg.paths.subagent_dir,
            parent_session_id=self.session_id,
            provider=provider,
            registry_getter=lambda: registry if registry is not None else ToolRegistry(),
            parent_max_steps=agent_max_steps,
            safety_gate=safety_gate,
            approver=approver,
            context_config=app_cfg.context,
            archive_dir=str(self.root / app_cfg.paths.archive_dir),
            gitstate_dir=self.root / app_cfg.paths.gitstate_dir,
            sink=sink,
        )
        registry = default_registry(
            memory_store=memory_store,
            sink=sink,
            job_log_dir=self.root / app_cfg.paths.job_dir,
            git_baseline_path=git_baseline_path,
            runtime_selection=runtime_selection,
            skill_store=skill_store,
            skill_runner=run_skill_subagent,
            task_runner=run_task_subagent,
            subagent_manager=subagents,
            attachment_store=AttachmentStore(self.root / ".attachments"),
            attachment_session_id=self.session_id,
        )
        agent = Agent(
            provider=provider,
            tools=registry,
            session=session,
            max_steps=agent_max_steps,
            safety_gate=safety_gate,
            approver=approver,
            context_config=app_cfg.context,
            archive_dir=str(self.root / app_cfg.paths.archive_dir),
            sink=sink,
            git_baseline_path=git_baseline_path,
            cancelled=self._cancel_event.is_set,
            show_thought_summary=app_cfg.ui.show_thought_summary,
        )
        return agent, store, session, sink

    def _load_or_create_session(
        self,
        store: Optional[SessionStore] = None,
        memory_store: Optional[AutoMemoryStore] = None,
        skill_store: Optional[SkillStore] = None,
    ) -> Session:
        with self._lock:
            if self._session is not None:
                return self._session
        store = store or self._session_store()
        if store.path_for(self.session_id).exists():
            session = store.load(self.session_id)
        else:
            session = self._new_session_object(memory_store=memory_store, skill_store=skill_store)
        with self._lock:
            self._session = session
        return session

    def _new_session_object(
        self,
        memory_store: Optional[AutoMemoryStore] = None,
        skill_store: Optional[SkillStore] = None,
    ) -> Session:
        self.env_loader(self.root)
        app_cfg = load_app_config(self.root / "mcode-config.json")
        memory_store = memory_store or AutoMemoryStore(self.root / app_cfg.paths.memory_dir)
        skill_store = skill_store or SkillStore(project_root=self.root, custom_paths=list(app_cfg.paths.skill_custom_dirs))
        memory = load_memory(self.root, auto_store=memory_store)
        system_prompt = compose_system_prompt(self.system_prompt, memory)
        system_prompt = apply_skill_index(system_prompt, skill_store.list())
        return Session(system_prompt)

    def _session_store(self) -> SessionStore:
        app_cfg = load_app_config(self.root / "mcode-config.json")
        return SessionStore(self.root / app_cfg.paths.session_dir)

    def _record_crash(self, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        data: dict[str, Any] = {"error": message}
        if isinstance(exc, ProviderError):
            data["provider_error"] = {
                "kind": exc.kind,
                "status_code": exc.status_code,
                "retryable": exc.retryable,
                "attempt": exc.attempt,
                "request_id": exc.request_id,
            }
        self._emit_lifecycle_event("turn_failed", data)
        self._emit_lifecycle_event("notice", {"message": f"UI turn failed: {message}"})

    def _emit_controller_started(self) -> None:
        self._emit_lifecycle_event(
            "controller_started",
            {
                "project_root": str(self.root),
                "session_id": self.session_id,
                "cwd": str(Path.cwd()),
                "runtime": runtime_to_dict(discover_runtime(self.root)),
            },
        )

    def _emit_lifecycle_event(self, kind: str, data: dict[str, Any]) -> None:
        try:
            app_cfg = load_app_config(self.root / "mcode-config.json")
            run_dir = self.root / app_cfg.paths.run_dir
        except Exception:
            run_dir = self.root / ".runs"
        sink = self._run_recorder(run_dir)
        sink.emit(Event(kind, data))

    def _run_recorder(self, run_dir: Path) -> RunRecorder:
        if self.recorder_factory is not None:
            return self.recorder_factory(run_dir, self.session_id, self.session_id)
        return RunRecorder(directory=run_dir, run_id=self.session_id, session_id=self.session_id)


class ControllerManager:
    def __init__(
        self,
        system_prompt: str,
        approver_factory: Optional[ApproverFactory] = None,
        env_loader: Optional[EnvLoader] = None,
        recorder_factory: Optional[RecorderFactory] = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.approver_factory = approver_factory
        self.env_loader = env_loader
        self.recorder_factory = recorder_factory
        self._controllers: dict[tuple[str, str], MiniController] = {}
        self._lock = threading.Lock()

    def get(self, root: str | Path, session_id: str) -> MiniController:
        root_path = Path(root).resolve()
        key = (str(root_path), session_id)
        with self._lock:
            controller = self._controllers.get(key)
            if controller is None:
                controller = MiniController(
                    root=root_path,
                    session_id=session_id,
                    system_prompt=self.system_prompt,
                    approver_factory=self.approver_factory,
                    env_loader=self.env_loader,
                    recorder_factory=self.recorder_factory,
                )
                self._controllers[key] = controller
            return controller

    def submit(
        self,
        root: str | Path,
        session_id: str,
        message: str,
        plan: bool = False,
        permission_mode: PermissionMode = "auto_review",
        attachment_ids: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        return self.get(root, session_id).submit(
            message,
            plan=plan,
            permission_mode=permission_mode,
            attachment_ids=attachment_ids,
        )

    def cancel(self, root: str | Path, session_id: str) -> dict[str, Any]:
        return self.get(root, session_id).cancel()

    def new_session(self, root: str | Path, label: str = "session") -> dict[str, Any]:
        root_path = Path(root).resolve()
        seed_id = f"new-{int(time.time() * 1000)}"
        controller = MiniController(
            root=root_path,
            session_id=seed_id,
            system_prompt=self.system_prompt,
            approver_factory=self.approver_factory,
            env_loader=self.env_loader,
        )
        result = controller.new_session(label)
        with self._lock:
            self._controllers[(str(root_path), controller.session_id)] = controller
        return result

    def snapshot(self, root: str | Path, session_id: str) -> ControllerSnapshot:
        return self.get(root, session_id).snapshot()


@contextlib.contextmanager
def _pushd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)
