from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

BACKEND_ROOT = Path(__file__).resolve().parent
APP_ROOT = Path(os.environ.get("MCODE_RUNTIME_ROOT", "")).expanduser() if os.environ.get("MCODE_RUNTIME_ROOT") else None
RUNTIME_ROOT = APP_ROOT if APP_ROOT and APP_ROOT.exists() else BACKEND_ROOT.parents[1]
for candidate in (BACKEND_ROOT, BACKEND_ROOT.parent, RUNTIME_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from event_reader import file_tree, list_sessions, read_events, read_file, read_jobs, read_session, read_subagents, read_summary
from mini_agent_lab.session_store import SessionStore
from event_broker import event_broker, stream_records
from change_review import confirm_latest_changes, undo_latest_change_file, undo_latest_changes
from project_store import APP_DATA_DIR, ProjectStore, ensure_inside_project, project_root, project_to_dict
from runtime import AgentRuntime
from system_bridge import open_file, pick_folder
from terminal_manager import TerminalManager
from test_runner import TestRunner
from settings_api import clear_api_key, read_policy_settings, read_project_settings, run_api_test, write_api_key, write_policy_settings, write_project_settings
from mini_agent_lab.attachments import AttachmentStore
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.events import Event
from mini_agent_lab.plan import build_approved_plan_message, parse_plan_todos
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.tool.todo import todo_event_data
from mini_agent_lab.runtime_env import discover_runtime, runtime_to_dict, save_runtime_override


app = FastAPI(title="Mcode UI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

projects = ProjectStore()
runtime = AgentRuntime()
tests = TestRunner()
terminals = TerminalManager()


class CreateProjectRequest(BaseModel):
    name: str = ""
    root_path: str


class SendMessageRequest(BaseModel):
    message: str
    plan: bool = False
    permission_mode: str = "auto_review"
    attachment_ids: list[str] = []


class CreateSessionRequest(BaseModel):
    label: str = "ui"


class RenameSessionRequest(BaseModel):
    label: str


class RunTestRequest(BaseModel):
    label: str = "subagent"


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class RuntimeUpdateRequest(BaseModel):
    python: Optional[str] = None
    shell: Optional[str] = None


class TerminalCreateRequest(BaseModel):
    shell: str = ""
    kind: str = "python"
    python: str = ""


class TerminalInputRequest(BaseModel):
    data: str


class ChangeFileRequest(BaseModel):
    path: str


class AttachmentUploadRequest(BaseModel):
    name: str
    content_base64: str
    mime_type: str = ""


class PlanApproveRequest(BaseModel):
    permission_mode: str = "auto_review"


class PlanRefineRequest(BaseModel):
    feedback: str


class PlanCancelRequest(BaseModel):
    reason: str = ""


class ApiTestRequest(BaseModel):
    count: int = 3


class ApiKeyRequest(BaseModel):
    value: str = ""


class OpenFileRequest(BaseModel):
    path: str
    app: str = ""


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/app/about")
def app_about():
    return {
        "name": "Mcode",
        "version": app.version,
        "backend_root": str(BACKEND_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "app_data_dir": str(APP_DATA_DIR),
        "frontend_dist": str(_frontend_dist()),
    }


@app.get("/api/projects")
def list_projects():
    return {"projects": [project_to_dict(project) for project in projects.list()]}


@app.post("/api/system/pick-folder")
def api_pick_folder():
    return pick_folder()


@app.get("/api/approvals")
def api_approvals(session_id: str = ""):
    return {"approvals": runtime.list_approvals(session_id=session_id)}


@app.post("/api/approvals/{approval_id}")
def api_decide_approval(approval_id: str, req: ApprovalDecisionRequest):
    try:
        return runtime.decide_approval(approval_id, req.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects")
def create_project(req: CreateProjectRequest):
    try:
        project, created = projects.create(name=req.name, root_path=req.root_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**project_to_dict(project), "created": created}


@app.get("/api/projects/{project_id}/sessions")
def api_list_sessions(project_id: str):
    project = _project(project_id)
    return {"sessions": list_sessions(project)}


@app.post("/api/projects/{project_id}/sessions")
def api_create_session(project_id: str, req: Optional[CreateSessionRequest] = None):
    label = req.label if req else "ui"
    return runtime.create_session(_project(project_id), label=label or "ui")


@app.get("/api/projects/{project_id}/sessions/{session_id}")
def api_read_session(project_id: str, session_id: str):
    try:
        return read_session(_project(project_id), session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/sessions/{session_id}")
def api_delete_session(project_id: str, session_id: str):
    store = SessionStore(project_root(_project(project_id)) / ".sessions")
    store.delete(session_id)
    return {"deleted": True}


@app.patch("/api/projects/{project_id}/sessions/{session_id}")
def api_rename_session(project_id: str, session_id: str, req: RenameSessionRequest):
    label = req.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label is required")
    store = SessionStore(project_root(_project(project_id)) / ".sessions")
    try:
        new_id = store.rename(session_id, label)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"renamed": True, "label": label, "id": new_id}


@app.post("/api/projects/{project_id}/sessions/{session_id}/messages")
def api_send_message(project_id: str, session_id: str, req: SendMessageRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return runtime.start_turn(
            _project(project_id),
            session_id,
            req.message,
            plan=req.plan,
            permission_mode=req.permission_mode,
            attachment_ids=req.attachment_ids,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/sessions/{session_id}/cancel")
def api_cancel_message(project_id: str, session_id: str):
    return runtime.cancel_turn(_project(project_id), session_id)


@app.get("/api/projects/{project_id}/sessions/{session_id}/controller")
def api_controller(project_id: str, session_id: str):
    return runtime.controller_snapshot(_project(project_id), session_id)


@app.get("/api/projects/{project_id}/sessions/{session_id}/summary")
def api_summary(project_id: str, session_id: str):
    return read_summary(_project(project_id), session_id)


@app.get("/api/projects/{project_id}/sessions/{session_id}/plan")
def api_get_plan(project_id: str, session_id: str):
    summary = read_summary(_project(project_id), session_id)
    return {"plan": summary.get("pending_plan")}


@app.post("/api/projects/{project_id}/sessions/{session_id}/plan/approve")
def api_approve_plan(project_id: str, session_id: str, req: PlanApproveRequest):
    project = _project(project_id)
    snapshot = runtime.controller_snapshot(project, session_id)
    if snapshot.get("running"):
        raise HTTPException(status_code=409, detail="session already has an active turn")
    pending_plan = _pending_plan(project_id, session_id)
    plan_text = str(pending_plan.get("plan_text") or "").strip()
    todo_items = pending_plan.get("todos")
    if not isinstance(todo_items, list):
        todo_items = parse_plan_todos(plan_text)
    message = build_approved_plan_message(plan_text, todo_items)
    recorder = _run_recorder(project, session_id)
    recorder.emit(
        Event(
            "plan_approved",
            {
                "plan_text": plan_text,
                "todos": todo_items,
                "revision": pending_plan.get("revision"),
            },
        )
    )
    if todo_items:
        recorder.emit(Event("todo_updated", todo_event_data({"todos": todo_items})))
    try:
        return runtime.start_turn(project, session_id, message, plan=False, permission_mode=req.permission_mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/sessions/{session_id}/plan/refine")
def api_refine_plan(project_id: str, session_id: str, req: PlanRefineRequest):
    if not req.feedback.strip():
        raise HTTPException(status_code=400, detail="feedback is required")
    project = _project(project_id)
    pending_plan = _pending_plan(project_id, session_id)
    plan_text = str(pending_plan.get("plan_text") or "").strip()
    revision = int(pending_plan.get("revision") or 1) + 1
    message = (
        "Revise the previous plan according to the user's feedback.\n\n"
        f"Previous plan:\n{plan_text}\n\n"
        f"User feedback:\n{req.feedback.strip()}\n\n"
        f"This should become plan revision {revision}.\n\n"
        "Return only the revised concise plan and stop."
    )
    try:
        return runtime.start_turn(project, session_id, message, plan=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/sessions/{session_id}/plan/cancel")
def api_cancel_plan(project_id: str, session_id: str, req: PlanCancelRequest):
    project = _project(project_id)
    pending_plan = _pending_plan(project_id, session_id)
    plan_text = str(pending_plan.get("plan_text") or "").strip()
    _run_recorder(project, session_id).emit(
        Event(
            "plan_cancelled",
            {"plan_text": plan_text, "reason": req.reason, "revision": pending_plan.get("revision")},
        )
    )
    return {"status": "cancelled", "session_id": session_id}


@app.get("/api/projects/{project_id}/sessions/{session_id}/events")
def api_events(project_id: str, session_id: str, limit: int = Query(400, ge=1, le=2000)):
    return {"events": read_events(_project(project_id), session_id, limit=limit)}


@app.get("/api/projects/{project_id}/sessions/{session_id}/stream")
def api_event_stream(project_id: str, session_id: str, last_seq: int = Query(0, ge=0)):
    project = _project(project_id)
    root = project_root(project)
    replay = read_events(project, session_id, limit=2000)
    return StreamingResponse(
        stream_records(event_broker, root, session_id, replay, last_seq=last_seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/projects/{project_id}/sessions/{session_id}/changes/confirm")
def api_confirm_changes(project_id: str, session_id: str):
    return confirm_latest_changes(_project(project_id), session_id)


@app.post("/api/projects/{project_id}/sessions/{session_id}/changes/undo")
def api_undo_changes(project_id: str, session_id: str):
    try:
        return undo_latest_changes(_project(project_id), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/sessions/{session_id}/changes/undo-file")
def api_undo_change_file(project_id: str, session_id: str, req: ChangeFileRequest):
    try:
        return undo_latest_change_file(_project(project_id), session_id, req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/sessions/{session_id}/subagents")
def api_subagents(project_id: str, session_id: str):
    return {"subagents": read_subagents(_project(project_id), session_id)}


@app.get("/api/projects/{project_id}/sessions/{session_id}/attachments")
def api_list_attachments(project_id: str, session_id: str):
    root = project_root(_project(project_id))
    store = AttachmentStore(root / ".attachments")
    return {"attachments": [meta.to_dict() for meta in store.list(session_id)]}


@app.post("/api/projects/{project_id}/sessions/{session_id}/attachments")
def api_upload_attachment(project_id: str, session_id: str, req: AttachmentUploadRequest):
    root = project_root(_project(project_id))
    try:
        meta = AttachmentStore(root / ".attachments").add_base64(
            session_id=session_id,
            name=req.name,
            content_base64=req.content_base64,
            mime_type=req.mime_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return meta.to_dict()


@app.get("/api/projects/{project_id}/sessions/{session_id}/attachments/{attachment_id}/preview")
def api_preview_attachment(project_id: str, session_id: str, attachment_id: str):
    root = project_root(_project(project_id))
    try:
        meta = AttachmentStore(root / ".attachments").get(session_id, attachment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta.to_dict()


@app.get("/api/projects/{project_id}/files/tree")
def api_file_tree(project_id: str, path: str = "", depth: int = Query(2, ge=1, le=5)):
    try:
        return file_tree(_project(project_id), rel_path=path, depth=depth)
    except (PermissionError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/files/read")
def api_read_file(project_id: str, path: str):
    try:
        return read_file(_project(project_id), path)
    except (PermissionError, FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/files/open")
def api_open_file(project_id: str, req: OpenFileRequest):
    project = _project(project_id)
    try:
        target = ensure_inside_project(project, req.path)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    app_cfg = load_app_config(project_root(project) / "mcode-config.json")
    result = open_file(target, req.app or app_cfg.ui.file_open_app)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason") or "failed to open file")
    return result


@app.get("/api/projects/{project_id}/jobs")
def api_jobs(project_id: str):
    return {"jobs": read_jobs(_project(project_id))}


@app.get("/api/projects/{project_id}/settings")
def api_settings(project_id: str):
    return read_project_settings(project_root(_project(project_id)))


@app.put("/api/projects/{project_id}/settings")
def api_update_settings(project_id: str, req: dict):
    try:
        return write_project_settings(project_root(_project(project_id)), req)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/settings/api-key")
def api_save_api_key(project_id: str, req: ApiKeyRequest):
    root = project_root(_project(project_id))
    try:
        write_api_key(req.value)
        return read_project_settings(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/settings/api-key")
def api_clear_api_key(project_id: str):
    root = project_root(_project(project_id))
    clear_api_key()
    return read_project_settings(root)


@app.post("/api/projects/{project_id}/settings/api-test")
def api_settings_api_test(project_id: str, req: ApiTestRequest):
    try:
        return run_api_test(project_root(_project(project_id)), count=req.count)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/settings/policy")
def api_policy_read(project_id: str):
    return read_policy_settings(project_root(_project(project_id)))


@app.put("/api/projects/{project_id}/settings/policy")
def api_policy_update(project_id: str, req: dict):
    try:
        return write_policy_settings(project_root(_project(project_id)), req)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/runtime")
def api_runtime(project_id: str):
    return runtime_to_dict(discover_runtime(project_root(_project(project_id))))


@app.post("/api/projects/{project_id}/runtime")
def api_update_runtime(project_id: str, req: RuntimeUpdateRequest):
    try:
        selection = save_runtime_override(project_root(_project(project_id)), python=req.python, shell=req.shell)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runtime_to_dict(selection)


@app.get("/api/projects/{project_id}/terminals")
def api_list_terminals(project_id: str):
    return {"terminals": terminals.list(project_root(_project(project_id)))}


@app.post("/api/projects/{project_id}/terminals")
def api_create_terminal(project_id: str, req: TerminalCreateRequest):
    root = project_root(_project(project_id))
    runtime_selection = discover_runtime(root)
    shell = req.shell or runtime_selection.shell
    python = req.python or runtime_selection.python
    try:
        return terminals.create(root, shell=shell, kind=req.kind, python=python)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/terminals/{terminal_id}/read")
def api_read_terminal(terminal_id: str, cursor: int = Query(0, ge=0)):
    try:
        return terminals.read(terminal_id, cursor=cursor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/terminals/{terminal_id}/input")
def api_write_terminal(terminal_id: str, req: TerminalInputRequest):
    try:
        return terminals.write(terminal_id, req.data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/terminals/{terminal_id}/close")
def api_close_terminal(terminal_id: str):
    try:
        return terminals.close(terminal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/tests/run")
def api_run_test(project_id: str, req: RunTestRequest):
    return tests.start(project_root(_project(project_id)), req.label)


@app.get("/api/projects/{project_id}/tests/{run_id}")
def api_get_test(project_id: str, run_id: str):
    _project(project_id)
    try:
        return tests.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _project(project_id: str):
    try:
        return projects.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _pending_plan(project_id: str, session_id: str) -> dict:
    summary = read_summary(_project(project_id), session_id)
    pending = summary.get("pending_plan")
    if not isinstance(pending, dict) or pending.get("status") != "awaiting_approval":
        raise HTTPException(status_code=404, detail="no pending plan for this session")
    plan_text = str(pending.get("plan_text") or "").strip()
    if not plan_text:
        raise HTTPException(status_code=404, detail="pending plan is empty")
    return pending


def _run_recorder(project, session_id: str) -> RunRecorder:
    root = project_root(project)
    cfg = load_app_config(root / "mcode-config.json")
    return RunRecorder(
        directory=root / cfg.paths.run_dir,
        run_id=session_id,
        session_id=session_id,
        record_downstream=lambda record: event_broker.publish(root, session_id, record),
    )


def _frontend_dist() -> Path:
    configured = os.environ.get("MCODE_FRONTEND_DIST", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (BACKEND_ROOT.parent / "frontend" / "dist").resolve(strict=False)


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    dist = _frontend_dist()
    if not dist.exists():
        raise HTTPException(status_code=404, detail=f"frontend dist not found: {dist}")
    target = (dist / full_path).resolve(strict=False) if full_path else dist / "index.html"
    try:
        target.relative_to(dist)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    if target.is_file():
        return FileResponse(target)
    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail=f"frontend index not found: {index}")
    return FileResponse(index)
