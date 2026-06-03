"""Tests for Mcode UI backend helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mcode-ui" / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from event_reader import file_tree, list_sessions, read_events, read_file, read_subagents, read_summary
from event_broker import EventBroker, stream_records
from approvals import ApprovalStore
from change_review import latest_change_review, undo_latest_change_file, undo_latest_changes
from project_store import ProjectStore, ensure_inside_project
from test_runner import TEST_COMMANDS, TestRunner
from mini_agent_lab.change import make_change
from mini_agent_lab.checkpoint import CheckpointStore
from fastapi.testclient import TestClient
import app as ui_api


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_frontend_dist_is_served_by_backend() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(tmp) / "dist"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        (dist / "index.html").write_text("<html><title>Mcode</title><div id=\"root\"></div></html>", encoding="utf-8")
        (dist / "mcode-logo.jpg").write_bytes(b"jpeg")
        (assets / "app.js").write_text("console.log('mcode')", encoding="utf-8")
        old_dist = os.environ.get("MCODE_FRONTEND_DIST")
        os.environ["MCODE_FRONTEND_DIST"] = str(dist)
        try:
            client = TestClient(ui_api.app)
            home = client.get("/")
            fallback = client.get("/sessions/demo")
            asset = client.get("/assets/app.js")
            logo = client.get("/mcode-logo.jpg")
            missing_api = client.get("/api/does-not-exist")
        finally:
            if old_dist is None:
                os.environ.pop("MCODE_FRONTEND_DIST", None)
            else:
                os.environ["MCODE_FRONTEND_DIST"] = old_dist

        _assert(home.status_code == 200 and "Mcode" in home.text, "backend serves frontend index")
        _assert(fallback.status_code == 200 and "root" in fallback.text, "backend falls back to index for app routes")
        _assert(asset.status_code == 200 and "mcode" in asset.text, "backend serves frontend assets")
        _assert(logo.status_code == 200 and logo.content == b"jpeg", "backend serves root frontend files")
        _assert(missing_api.status_code == 404, "unknown API routes still return 404")


def test_app_about_endpoint_reports_runtime_paths() -> None:
    client = TestClient(ui_api.app)
    response = client.get("/api/app/about")
    _assert(response.status_code == 200, "app about endpoint succeeds")
    payload = response.json()
    _assert(payload["name"] == "Mcode", "app about reports app name")
    _assert(payload["backend_root"], "app about reports backend root")
    _assert(payload["app_data_dir"], "app about reports app data dir")


def test_project_store_default_create_and_path_guard() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = ProjectStore(tmp_path / "projects.json")
        default = store.list()[0]
        created, was_created = store.create(name="Demo Project", root_path=str(tmp_path))
        duplicate, duplicate_created = store.create(name="Different Name", root_path=str(tmp_path))

        _assert(default.id == "mcode", "default project exists")
        _assert(created.id == "Demo-Project", "project id is sanitized")
        _assert(was_created is True, "new project reports created")
        _assert(duplicate.id == created.id, "duplicate project path returns existing project")
        _assert(duplicate_created is False, "duplicate project path reports not created")
        _assert((tmp_path / "projects.json").exists(), "project store is persisted")
        _assert(ensure_inside_project(created, ".").exists(), "inside project path is allowed")
        try:
            ensure_inside_project(created, "../escape")
            raise AssertionError("escape path should fail")
        except PermissionError:
            print("  OK: project path escape is rejected")


def test_event_reader_sessions_summary_events_files_subagents() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, _ = ProjectStore(tmp_path / "store.json").create(name="demo", root_path=str(tmp_path))
        (tmp_path / ".sessions").mkdir()
        (tmp_path / ".sessions" / "s1.jsonl").write_text(
            json.dumps({"role": "user", "content": "hello"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (tmp_path / ".runs").mkdir()
        (tmp_path / ".runs" / "s1.summary.json").write_text('{"status":"completed"}', encoding="utf-8")
        (tmp_path / ".runs" / "s1.events.jsonl").write_text(
            json.dumps({"kind": "turn_completed", "data": {"answer": "ok"}}) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("readme", encoding="utf-8")
        sub = tmp_path / ".subagents" / "s1" / "sub-1"
        sub.mkdir(parents=True)
        state = {"subagent_id": "sub-1", "status": "completed", "events_path": str(sub / "events.jsonl")}
        (sub / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (sub / "events.jsonl").write_text(json.dumps({"kind": "subagent_completed", "data": {}}) + "\n", encoding="utf-8")

        _assert(list_sessions(project)[0]["id"] == "s1", "sessions are listed")
        _assert(read_summary(project, "s1")["status"] == "completed", "summary is read")
        _assert(read_events(project, "s1")[0]["kind"] == "turn_completed", "events are read")
        _assert(read_file(project, "README.md")["content"] == "readme", "project file is read")
        _assert(file_tree(project)["is_dir"] is True, "file tree is returned")
        _assert(read_subagents(project, "s1")[0]["subagent_id"] == "sub-1", "subagents are aggregated")


def test_event_broker_stream_replays_and_fans_out_records() -> None:
    broker = EventBroker()
    replay = [{"seq": 4, "kind": "turn_status", "data": {"phase": "model_call"}}]
    stream = stream_records(broker, "/tmp/mcode-project", "s1", replay, last_seq=3)
    first = next(stream)
    _assert("id: 4" in first and '"kind": "turn_status"' in first, "SSE stream replays records after last seq")
    broker.publish("/tmp/mcode-project", "s1", {"seq": 5, "kind": "assistant_delta", "data": {"delta": "ok"}})
    second = next(stream)
    stream.close()
    _assert("id: 5" in second and '"assistant_delta"' in second, "SSE stream fans out live records")


def test_event_broker_drops_oldest_for_slow_subscribers() -> None:
    broker = EventBroker()
    subscriber = broker.subscribe("/tmp/mcode-project", "s1")
    for seq in range(250):
        broker.publish("/tmp/mcode-project", "s1", {"seq": seq, "kind": "turn_status", "data": {}})
    records = []
    while not subscriber.empty():
        records.append(subscriber.get_nowait())
    broker.unsubscribe("/tmp/mcode-project", "s1", subscriber)

    _assert(len(records) == 200, "SSE broker caps queued records for slow subscribers")
    _assert(records[-1]["seq"] == 249, "SSE broker keeps the newest record when dropping old events")


def test_test_runner_runs_subagent_test() -> None:
    runner = TestRunner()
    run = runner.start(ROOT, "subagent")
    deadline = time.time() + 20
    result = runner.get(run["id"])
    while result["status"] == "running" and time.time() < deadline:
        time.sleep(0.1)
        result = runner.get(run["id"])
    _assert(result["status"] == "completed", "test runner completes subagent test")
    _assert("All subagent tests passed." in result["output"], "test runner captures output")


def test_test_runner_exposes_product_acceptance() -> None:
    runner = TestRunner()
    run = runner.start(ROOT, "product")
    _assert(run["label"] == "product", "test runner exposes product acceptance label")
    _assert(run["command"] == ["python3", "scripts/product_acceptance.py"], "product acceptance command is configured")
    _assert("benchmark-dry" in TEST_COMMANDS, "test runner exposes benchmark dry label")
    _assert(
        TEST_COMMANDS["benchmark-dry"] == ["python3", "scripts/run_product_benchmark_suite.py", "--dry-run"],
        "benchmark dry command is configured",
    )
    _assert("benchmark" in TEST_COMMANDS, "test runner exposes full benchmark label")
    _assert(TEST_COMMANDS["benchmark"] == ["python3", "scripts/run_product_benchmark_suite.py"], "full benchmark command is configured")


def test_approval_store_decision_flow() -> None:
    store = ApprovalStore()
    item = store.create(session_id="s1", tool_name="bash", arguments={"command": "echo ok"}, reason="bash ask")
    _assert(store.list(session_id="s1")[0]["id"] == item.id, "approval store lists pending approval")
    decided = store.decide(item.id, True)
    _assert(decided.approved is True, "approval store records allow decision")
    _assert(store.wait(item.id, timeout_seconds=0) is True, "approval store wait returns decision")


def test_change_review_undo_restores_latest_turn() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, _ = ProjectStore(tmp_path / "store.json").create(name="demo", root_path=str(tmp_path))
        checkpoint = CheckpointStore(tmp_path / ".checkpoints").save(
            make_change("demo.txt", None, "hello\n"),
            "write_file",
            {"path": "demo.txt", "content": "hello\n"},
        )
        (tmp_path / "demo.txt").write_text("hello\n", encoding="utf-8")
        (tmp_path / ".runs").mkdir()
        events = [
            {"seq": 1, "kind": "turn_started", "data": {"input": "write"}},
            {
                "seq": 2,
                "kind": "preview",
                "data": {"kind": "create", "path": "demo.txt", "diff": "--- /dev/null\n+++ b/demo.txt\n+hello\n"},
            },
            {"seq": 3, "kind": "checkpoint_saved", "data": {"id": checkpoint.id, "path": "demo.txt"}},
            {"seq": 4, "kind": "turn_completed", "data": {"answer": "done"}},
        ]
        (tmp_path / ".runs" / "s1.events.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            encoding="utf-8",
        )

        review = latest_change_review(project, "s1")
        _assert(review["files"] == 1, "change review finds latest changed file")
        _assert(review["additions"] == 1, "change review counts additions")
        result = undo_latest_changes(project, "s1")
        _assert(result["status"] == "reverted", "change review undo reports reverted")
        _assert(not (tmp_path / "demo.txt").exists(), "undo restores created file by deleting it")


def test_change_review_undo_restores_single_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project, _ = ProjectStore(tmp_path / "store.json").create(name="demo", root_path=str(tmp_path))
        checkpoint_a = CheckpointStore(tmp_path / ".checkpoints").save(
            make_change("a.txt", None, "a\n"),
            "write_file",
            {"path": "a.txt", "content": "a\n"},
        )
        time.sleep(0.002)
        checkpoint_b = CheckpointStore(tmp_path / ".checkpoints").save(
            make_change("b.txt", None, "b\n"),
            "write_file",
            {"path": "b.txt", "content": "b\n"},
        )
        (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
        (tmp_path / ".runs").mkdir()
        events = [
            {"seq": 1, "kind": "turn_started", "data": {"input": "write"}},
            {"seq": 2, "kind": "preview", "data": {"kind": "create", "path": "a.txt", "diff": "+a\n"}},
            {"seq": 3, "kind": "checkpoint_saved", "data": {"id": checkpoint_a.id, "path": "a.txt"}},
            {"seq": 4, "kind": "preview", "data": {"kind": "create", "path": "b.txt", "diff": "+b\n"}},
            {"seq": 5, "kind": "checkpoint_saved", "data": {"id": checkpoint_b.id, "path": "b.txt"}},
            {"seq": 6, "kind": "turn_completed", "data": {"answer": "done"}},
        ]
        (tmp_path / ".runs" / "s1.events.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            encoding="utf-8",
        )

        result = undo_latest_change_file(project, "s1", "a.txt")
        review = latest_change_review(project, "s1")
        _assert(result["status"] == "file_reverted", "single file undo reports reverted")
        _assert(not (tmp_path / "a.txt").exists(), "single file undo restores target")
        _assert((tmp_path / "b.txt").exists(), "single file undo leaves other file")
        _assert(review["changes"][0]["status"] == "reverted", "single file review marks reverted file")


def test_plan_api_reads_and_cancels_pending_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        old_projects = ui_api.projects
        ui_api.projects = ProjectStore(tmp_path / "ui-projects.json")
        try:
            project, _ = ui_api.projects.create(name="plan-api-demo", root_path=str(tmp_path))
            runs = tmp_path / ".runs"
            runs.mkdir()
            (runs / "s1.summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "s1",
                        "session_id": "s1",
                        "status": "awaiting_plan_decision",
                        "pending_plan": {"status": "awaiting_approval", "plan_text": "1. Inspect\n2. Implement"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            client = TestClient(ui_api.app)
            plan = client.get(f"/api/projects/{project.id}/sessions/s1/plan")
            cancelled = client.post(f"/api/projects/{project.id}/sessions/s1/plan/cancel", json={})
            summary = json.loads((runs / "s1.summary.json").read_text(encoding="utf-8"))
        finally:
            ui_api.projects = old_projects

        _assert(plan.status_code == 200, "plan API returns pending plan")
        _assert(plan.json()["plan"]["plan_text"].startswith("1. Inspect"), "plan API exposes plan text")
        _assert(cancelled.status_code == 200, "plan cancel API succeeds")
        _assert(summary["pending_plan"]["status"] == "cancelled", "plan cancel writes cancelled state")


def test_plan_approve_api_seeds_todo_from_pending_plan() -> None:
    class FakeRuntime:
        def __init__(self) -> None:
            self.started_message = ""

        def controller_snapshot(self, project, session_id: str) -> dict:
            return {"session_id": session_id, "running": False}

        def start_turn(self, project, session_id: str, message: str, plan: bool = False, permission_mode: str = "auto_review"):
            self.started_message = message
            return {"status": "started", "session_id": session_id, "plan": plan, "permission_mode": permission_mode}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        old_projects = ui_api.projects
        old_runtime = ui_api.runtime
        fake_runtime = FakeRuntime()
        ui_api.projects = ProjectStore(tmp_path / "ui-projects.json")
        ui_api.runtime = fake_runtime
        try:
            project, _ = ui_api.projects.create(name="plan-approve-demo", root_path=str(tmp_path))
            runs = tmp_path / ".runs"
            runs.mkdir()
            (runs / "s1.summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "s1",
                        "session_id": "s1",
                        "status": "awaiting_plan_decision",
                        "pending_plan": {
                            "status": "awaiting_approval",
                            "plan_text": "1. Inspect\n2. Implement\n3. Test",
                            "revision": 2,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            client = TestClient(ui_api.app)
            approved = client.post(f"/api/projects/{project.id}/sessions/s1/plan/approve", json={})
            summary = json.loads((runs / "s1.summary.json").read_text(encoding="utf-8"))
        finally:
            ui_api.projects = old_projects
            ui_api.runtime = old_runtime

        _assert(approved.status_code == 200, "plan approve API succeeds")
        _assert("Initial todo_write arguments" in fake_runtime.started_message, "approved turn receives todo seed")
        _assert("Approved plan:\n1. Inspect" in fake_runtime.started_message, "approved turn includes plan text")
        _assert("complete_step" in fake_runtime.started_message, "approved turn includes evidence sign-off rule")
        _assert(summary["pending_plan"]["status"] == "approved", "approved plan state is recorded")
        _assert(summary["pending_plan"]["revision"] == 2, "approved plan preserves revision")
        _assert(summary["todo"]["total"] == 3, "approved plan seeds summary todo")
        _assert(summary["todo"]["current"]["content"] == "Inspect", "first approved todo is in progress")


if __name__ == "__main__":
    test_frontend_dist_is_served_by_backend()
    test_app_about_endpoint_reports_runtime_paths()
    test_project_store_default_create_and_path_guard()
    test_event_reader_sessions_summary_events_files_subagents()
    test_event_broker_stream_replays_and_fans_out_records()
    test_event_broker_drops_oldest_for_slow_subscribers()
    test_test_runner_runs_subagent_test()
    test_test_runner_exposes_product_acceptance()
    test_approval_store_decision_flow()
    test_change_review_undo_restores_latest_turn()
    test_change_review_undo_restores_single_file()
    test_plan_api_reads_and_cancels_pending_plan()
    test_plan_approve_api_seeds_todo_from_pending_plan()
    print("All UI backend tests passed.")
