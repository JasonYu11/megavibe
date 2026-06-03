from __future__ import annotations

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.compact import compact_session, session_chars
from mini_agent_lab.config import load_config
from mini_agent_lab.events import Event, PrintSink
from mini_agent_lab.memory import AutoMemoryStore, compose_system_prompt, load_memory
from mini_agent_lab.plan import build_approved_plan_message, plan_todo_event_data
from mini_agent_lab.provider import DeepSeekProvider
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.session_store import SessionStore
from mini_agent_lab.skill import Skill, SkillStore, apply_skill_index, render_skill
from mini_agent_lab.subagent_manager import SubagentManager
from mini_agent_lab.tool import default_registry
from mini_agent_lab.tool.registry import ToolRegistry


SYSTEM_PROMPT = """You are Mcode, a learning coding agent.

Use tools when they help answer accurately.
When asked about local files, call read_file instead of guessing.
After tool results come back, answer the user from the results clearly and briefly.

## Tool Guidance
- For Python execution, use python_run instead of bash for .py files, pytest, python -m modules, and short Python snippets.
- Use bash only for non-Python shell tasks or commands that truly need a shell.
- write_file and edit_file automatically run a quick syntax check (py_compile / tsc --noEmit).
  If the result shows ⚠️ static check issues, fix them before proceeding. Never run code with static check failures.
- Use web_search for facts, API parameters, version requirements, and domain knowledge beyond your cutoff.
- Use official_docs_search(product, query) for official documentation on packages, frameworks, and platforms.
  Known products: python, react, vite, node, fastapi, openai, deepseek, swift, tailwindcss, nextjs, and more.
- For multi-step work, proactively use todo_write to maintain visible progress.
- Keep at most one todo in_progress at a time.
- Mark completed items promptly; do not batch all completions at the end.
- Skip todo_write for trivial single-step requests.

## Work Protocol

For non-trivial engineering tasks (multiple files, debugging, implementation, review):

1. Clarify the objective in one sentence before acting.
2. Inspect relevant code, tests, and docs before editing — never guess.
3. Form a working plan when the task has multiple steps; keep it executable.
4. Execute incrementally: state what you are changing and why before each edit.
5. Preserve evidence: record key commands, test results, artifacts.
6. Verify against the user's success criteria, not just "build passes".
7. Deliver with the Final Answer Contract below.

Reasoning visibility:
- OK: "I am checking the provider config" / "The failure comes from auth" / "I will add a test first"
- NOT OK: raw provider reasoning_content, lengthy chain-of-thought, unfiltered internal logs

## Final Answer Contract

For completed coding tasks, structure your final answer as:

已完成 <one-sentence outcome>。

改动重点：
- <file/module>: <user-visible behavior change>

验证：
- <command>: 通过 / 失败 (<N> tests passed)

运行状态：
- <local URL or artifact path>

注意：
- <risks, skipped checks, external dependencies>

Keep it concise. For trivial changes, 1-2 paragraphs is fine.
Never claim a validation you did not run.
If blocked, say what blocked you and what was verified.

## Handoff Examples

Implementation:
```
已完成 trace UI 组件拆分，AgentRunBlock 不再承载全部展示逻辑。

新增：
- ThoughtSummaryPanel.tsx / TraceStepList.tsx / TraceActionItem.tsx
- StreamingAssistantMessage.tsx / traceUi.tsx

验证：
- npm test：15 files / 79 tests passed
- npm run build：通过
- python3 scripts/product_acceptance.py：15/15 通过

本地服务：
- http://127.0.0.1:8018/
```

Debug:
```
问题定位：SSE replay 和 polling fallback 同时返回同一批 delta 时，
runTrace 会重复拼接 assistant draft。

修复：
- runTrace.ts 增加事件去重入口
- 无 seq 事件按 kind + data 去重，保持相对顺序
- assistant draft 按 message_id 隔离

验证：
- npm test -- runTrace.test.ts：通过
- npm test：79 tests passed
```

Blocked:
```
实现已完成，但真实 provider streaming QA 还不能验证。

原因：当前 DeepSeek API key 返回 401 authentication failure。

已验证：
- mock streaming provider 产生 assistant_delta / completed / turn_completed
- provider failure trace 在 UI 中恢复显示

继续前需要：在 Settings 中配置有效 API key。
```"""




def run_plan_flow(agent: Agent, task: str) -> str:
    agent.sink.emit(Event("notice", {"message": "plan mode enabled"}))
    agent.set_plan_mode(True)
    try:
        plan = agent.run(task)
    finally:
        agent.set_plan_mode(False)

    print(f"assistant plan>\n{plan}\n")
    approval = input("Approve this plan and execute it? [y/N] ").strip().lower()
    if approval not in {"y", "yes"}:
        return "plan not approved; no changes made"

    event_data = plan_todo_event_data(plan)
    if event_data:
        agent.sink.emit(Event("todo_updated", event_data))
        agent.sink.emit(Event("plan_seeded", {"todos": event_data["todos"]}))
    else:
        agent.sink.emit(Event("notice", {"message": "approved plan had no parseable markdown list; no todo seed"}))

    return agent.run(build_approved_plan_message(plan, event_data["todos"] if event_data else None))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mcode agent chat")
    parser.add_argument("message", nargs="*", help="Optional one-shot message")
    parser.add_argument("--session", help="Session id to save to")
    parser.add_argument("--resume", help="Resume an existing session id")
    parser.add_argument("--list-sessions", action="store_true", help="List saved sessions")
    parser.add_argument("--plan", action="store_true", help="Run the one-shot message through plan mode")
    args = parser.parse_args()

    app_cfg = load_app_config()
    store = SessionStore(app_cfg.paths.session_dir)
    if args.list_sessions:
        sessions = store.list()
        if not sessions:
            print("(no sessions)")
            return 0
        for info in sessions:
            print(f"{info.id}  messages={info.messages}  path={info.path}")
        return 0

    cfg = load_config()
    memory_store = AutoMemoryStore(app_cfg.paths.memory_dir)
    skill_store = SkillStore(project_root=ROOT, custom_paths=list(app_cfg.paths.skill_custom_dirs))
    skills = skill_store.list()
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=cfg.temperature,
    )
    if args.resume:
        session_id = args.resume
        session = store.load(session_id)
        print(f"[session] resumed {session_id}")
    else:
        session_id = args.session or store.new_id("agent")
        memory = load_memory(ROOT, auto_store=memory_store)
        system_prompt = compose_system_prompt(SYSTEM_PROMPT, memory)
        system_prompt = apply_skill_index(system_prompt, skills)
        session = Session(system_prompt)
        print(f"[session] using {session_id}")
        if memory.paths:
            loaded = ", ".join(path.name for path in memory.paths)
            print(f"[memory] loaded {loaded}")
        if skills:
            print(f"[skills] loaded {len(skills)} skill(s)")

    sink = RunRecorder(
        directory=app_cfg.paths.run_dir,
        run_id=session_id,
        session_id=session_id,
        downstream=PrintSink(),
    )
    git_baseline_path = Path(app_cfg.paths.gitstate_dir) / f"{session_id}.baseline.json"
    print(f"[run] events {sink.event_path}")
    print(f"[run] summary {sink.summary_path}")
    registry: ToolRegistry | None = None
    safety_gate = SafetyGate()
    approver = Approver(sink=sink)

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
        root_dir=app_cfg.paths.subagent_dir,
        parent_session_id=session_id,
        provider=provider,
        registry_getter=lambda: registry if registry is not None else ToolRegistry(),
        parent_max_steps=cfg.max_steps,
        safety_gate=safety_gate,
        approver=approver,
        context_config=app_cfg.context,
        archive_dir=app_cfg.paths.archive_dir,
        gitstate_dir=app_cfg.paths.gitstate_dir,
        sink=sink,
    )

    registry = default_registry(
        memory_store=memory_store,
        sink=sink,
        job_log_dir=app_cfg.paths.job_dir,
        git_baseline_path=git_baseline_path,
        skill_store=skill_store,
        skill_runner=run_skill_subagent,
        task_runner=run_task_subagent,
        subagent_manager=subagents,
    )
    agent = Agent(
        provider=provider,
        tools=registry,
        session=session,
        max_steps=cfg.max_steps,
        safety_gate=safety_gate,
        approver=approver,
        context_config=app_cfg.context,
        archive_dir=app_cfg.paths.archive_dir,
        sink=sink,
        git_baseline_path=git_baseline_path,
    )

    if args.message:
        message = " ".join(args.message)
        answer = run_plan_flow(agent, message) if args.plan else agent.run(message)
        path = store.save(session_id, session)
        print(f"[session] saved {session_id} -> {path}")
        print(f"assistant> {answer}")
        return 0

    print("Mcode agent chat")
    print(
        "Type /exit to quit, /history to inspect the current session, "
        "/plan <task> to plan, /skills to list skills, /skill <name> [args] to invoke.\n"
    )

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user in {"/exit", "/quit"}:
            return 0
        if user == "/history":
            for i, msg in enumerate(session.messages):
                print(f"{i:02d} {msg.role}: {msg.content}")
            continue
        if user == "/save":
            path = store.save(session_id, session)
            print(f"[session] saved {session_id} -> {path}")
            continue
        if user == "/compact":
            result = compact_session(
                session,
                recent_keep=app_cfg.context.recent_keep,
                archive_dir=app_cfg.paths.archive_dir,
                force=True,
                provider=provider,
                context_config=app_cfg.context,
            )
            if result.changed:
                path = store.save(session_id, session)
                print(f"[compact] archived to {result.archive_path}")
                print(f"[compact] messages {result.original_messages} -> {result.kept_messages}")
                print(f"[session] saved {session_id} -> {path}")
            else:
                print("[compact] nothing to compact")
            continue
        if user == "/context":
            chars = session_chars(session)
            print(f"[context] chars={chars} trigger_chars={app_cfg.context.trigger_chars}")
            continue
        if user == "/skills":
            for skill in skill_store.list():
                tag = " [subagent]" if skill.run_as == "subagent" else ""
                print(f"{skill.name}{tag} ({skill.scope}) - {skill.description}")
            continue
        if user.startswith("/skill "):
            text = user.removeprefix("/skill ").strip()
            if not text:
                print("Usage: /skill <name> [arguments]")
                continue
            name, _, skill_args = text.partition(" ")
            skill = skill_store.read(name)
            if skill is None:
                print(f"unknown skill: {name}")
                continue
            if skill.run_as == "subagent":
                answer = run_skill_subagent(skill, skill_args)
                print(f"assistant> {answer}\n")
                continue
            answer = agent.run(render_skill(skill, skill_args))
            path = store.save(session_id, session)
            print(f"[session] saved {session_id} -> {path}")
            print(f"assistant> {answer}\n")
            continue
        if user.startswith("/plan "):
            task = user.removeprefix("/plan ").strip()
            if not task:
                print("Usage: /plan <task>")
                continue
            answer = run_plan_flow(agent, task)
            path = store.save(session_id, session)
            print(f"[session] saved {session_id} -> {path}")
            print(f"assistant> {answer}\n")
            continue

        answer = agent.run(user)
        path = store.save(session_id, session)
        print(f"[session] saved {session_id} -> {path}")
        print(f"assistant> {answer}\n")


if __name__ == "__main__":
    raise SystemExit(main())
