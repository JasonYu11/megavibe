from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from mini_agent_lab.jobs import JobManager
from mini_agent_lab.change import make_change, read_existing
from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.memory import AutoMemoryStore
from mini_agent_lab.runtime_env import RuntimeSelection, discover_runtime
from mini_agent_lab.skill import SkillStore
from mini_agent_lab.tool.base import JsonObject, Tool
from mini_agent_lab.tool.attachments import ListAttachmentsTool, ReadAttachmentTool
from mini_agent_lab.tool.complete_step import CompleteStepTool
from mini_agent_lab.workspace_changes import diff_workspace, snapshot_workspace
from mini_agent_lab.tool.git_tools import (
    GitBaselineTool,
    GitClassifyChangesTool,
    GitCommitTool,
    GitDiffTool,
    GitStatusTool,
)
from mini_agent_lab.tool.memory import ListMemoryTool, RememberTool
from mini_agent_lab.tool.registry import ToolRegistry
from mini_agent_lab.tool.skill_tools import InstallSkillTool, ListSkillsTool, ReadSkillTool, RunSkillTool, SubagentRunner
from mini_agent_lab.tool.task import TaskRunner, TaskTool
from mini_agent_lab.tool.todo import TodoWriteTool


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Return the provided text. Useful for testing tool plumbing."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to return"},
            },
            "required": ["text"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        return str(arguments.get("text", ""))


class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read a UTF-8 text file with optional line offset and limit."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "0-based line offset", "minimum": 0},
                "limit": {"type": "integer", "description": "Maximum lines to return", "minimum": 1},
            },
            "required": ["path"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        path = arguments.get("path")
        if not path:
            raise ValueError("path is required")
        offset = int(arguments.get("offset", 0))
        limit = int(arguments.get("limit", 200))
        if offset < 0:
            offset = 0
        if limit <= 0:
            limit = 200

        file_path = Path(path)
        if file_path.is_dir():
            raise ValueError(f"{path} is a directory")
        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines:
            return "(empty file)"
        selected = lines[offset : offset + limit]
        if not selected:
            return f"(offset {offset} is past EOF; file has {len(lines)} lines)"

        width = len(str(offset + len(selected)))
        body = "\n".join(f"{i + offset + 1:>{width}}| {line}" for i, line in enumerate(selected))
        remaining = len(lines) - (offset + len(selected))
        if remaining > 0:
            body += f"\n\n[{remaining} more line(s); pass offset={offset + len(selected)} to continue]"
        return body


class ListDirTool(Tool):
    @property
    def name(self) -> str:
        return "ls"

    @property
    def description(self) -> str:
        return "List files and directories at a path."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
            },
            "required": ["path"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        path = Path(arguments.get("path") or ".")
        if not path.exists():
            raise ValueError(f"{path} does not exist")
        if not path.is_dir():
            raise ValueError(f"{path} is not a directory")

        entries = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            suffix = "/" if child.is_dir() else ""
            entries.append(f"{child.name}{suffix}")
        return "\n".join(entries) if entries else "(empty directory)"


class GlobTool(Tool):
    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files by glob pattern, such as '**/*.py' or 'mini_agent_lab/**/*.py'."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "limit": {"type": "integer", "description": "Maximum matches to return", "minimum": 1},
            },
            "required": ["pattern"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        pattern = arguments.get("pattern")
        if not pattern:
            raise ValueError("pattern is required")
        limit = int(arguments.get("limit", 100))
        if limit <= 0:
            limit = 100

        pattern = _workspace_glob(pattern)
        matches = sorted(str(p) for p in Path(".").glob(pattern))
        shown = matches[:limit]
        if not shown:
            return "(no matches)"
        body = "\n".join(shown)
        if len(matches) > len(shown):
            body += f"\n\n[{len(matches) - len(shown)} more match(es); narrow the pattern or increase limit]"
        return body


class GrepTool(Tool):
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search text files for a substring, optionally under a glob pattern."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text substring to search for"},
                "path_glob": {
                    "type": "string",
                    "description": "File glob to search, default '**/*'",
                },
                "limit": {"type": "integer", "description": "Maximum matching lines", "minimum": 1},
            },
            "required": ["pattern"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        pattern = arguments.get("pattern")
        if not pattern:
            raise ValueError("pattern is required")
        path_glob = _workspace_glob(str(arguments.get("path_glob") or "**/*"))
        limit = int(arguments.get("limit", 100))
        if limit <= 0:
            limit = 100

        try:
            regex = re.compile(pattern)
        except re.error:
            regex = None
        hits = []
        for path in sorted(Path(".").glob(path_glob)):
            if len(hits) >= limit:
                break
            if not path.is_file() or _looks_binary(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if (regex.search(line) if regex else pattern in line):
                    hits.append(f"{path}:{line_no}: {line}")
                    if len(hits) >= limit:
                        break

        if not hits:
            return "(no matches)"
        body = "\n".join(hits)
        if len(hits) >= limit:
            body += f"\n\n[stopped at limit={limit}; narrow path_glob or pattern for more precise results]"
        return body



def _quick_static_check(path: str) -> str:
    """Run a fast syntax-only check on a source file. Returns empty string if no issues."""
    suffix = Path(path).suffix
    cmd: list[str] | None = None
    if suffix == ".py":
        if shutil.which("python3"):
            cmd = ["python3", "-m", "py_compile", path]
        elif shutil.which("python"):
            cmd = ["python", "-m", "py_compile", path]
        else:
            cmd = [sys.executable, "-m", "py_compile", path]
    elif suffix in (".ts", ".tsx"):
        # prefer local tsc if available
        tsc = shutil.which("npx")
        if tsc:
            cmd = ["npx", "--yes", "typescript", "tsc", "--noEmit", "--pretty", path]
    elif suffix in (".js", ".mjs"):
        node = shutil.which("node")
        if node:
            cmd = [node, "--check", path]

    if not cmd:
        return ""

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            cwd=Path(path).parent,
        )
        if result.returncode == 0:
            return "\n🔍 static check passed"
        stderr = (result.stderr or result.stdout).strip()
        lines = stderr.split("\n")
        # keep first 10 lines
        short = "\n".join(lines[:10])
        if len(lines) > 10:
            short += f"\n... ({len(lines) - 10} more lines)"
        return f"\n⚠️  static check found issues:\n{short}"
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""


class EditFileTool(Tool):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace an exact string in a UTF-8 text file. old_string must occur exactly once."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace; must occur exactly once",
                },
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def execute(self, arguments: JsonObject) -> str:
        change = self.preview(arguments)
        file_path = Path(change.path)
        file_path.write_text(change.after, encoding="utf-8")
        old_lines = arguments.get("old_string", "").count("\n")
        new_lines = arguments.get("new_string", "").count("\n")
        delta = new_lines - old_lines
        added = max(0, delta)
        removed = max(0, -delta)
        diff_str = ""
        if added or removed:
            parts = []
            if added: parts.append(f"+{added}")
            if removed: parts.append(f"-{removed}")
            diff_str = f" ({' '.join(parts)} lines)"
        result = f"edited {file_path}{diff_str}"
        check = _quick_static_check(change.path)
        if check:
            result += check
        return result

    def preview(self, arguments: JsonObject):
        path = arguments.get("path")
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not path:
            raise ValueError("path is required")
        if old is None or old == "":
            raise ValueError("old_string is required")
        if new is None:
            raise ValueError("new_string is required")

        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        count = content.count(str(old))
        if count == 0:
            raise ValueError(f"old_string not found in {file_path}")
        if count > 1:
            raise ValueError(f"old_string is not unique in {file_path}; add more surrounding context")
        after = content.replace(str(old), str(new), 1)
        return make_change(str(file_path), content, after)


class WriteFileTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write UTF-8 text to a file, creating parent directories when needed."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        }

    def execute(self, arguments: JsonObject) -> str:
        change = self.preview(arguments)
        file_path = Path(change.path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(change.after, encoding="utf-8")
        content = str(arguments.get("content", ""))
        lines = content.count("\n") + (1 if content else 0)
        result = f"wrote {file_path} (+{lines} lines)"
        check = _quick_static_check(change.path)
        if check:
            result += check
        return result

    def preview(self, arguments: JsonObject):
        path = arguments.get("path")
        if not path:
            raise ValueError("path is required")
        content = arguments.get("content")
        if content is None:
            raise ValueError("content is required")

        before = read_existing(str(path))
        return make_change(str(path), before, str(content))


class BashTool(Tool):
    def __init__(
        self,
        jobs: Optional[JobManager] = None,
        sink: Optional[EventSink] = None,
        runtime: Optional[RuntimeSelection] = None,
    ) -> None:
        self.jobs = jobs
        self.sink = sink or NullSink()
        self.runtime = runtime or discover_runtime(Path.cwd())

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return combined stdout/stderr. "
            "Use this for non-Python shell work. Do not use it for Python scripts, pytest, "
            "python -m modules, or Python snippets; use python_run for those."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run detached and return a job id immediately. Use bash_output, wait, or kill_shell to manage it.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum seconds to wait before terminating the command",
                    "minimum": 1,
                },
            },
            "required": ["command"],
        }

    def execute(self, arguments: JsonObject) -> str:
        command = arguments.get("command")
        if not command:
            raise ValueError("command is required")
        if arguments.get("run_in_background"):
            if self.jobs is None:
                raise ValueError("background jobs are not available")
            job = self.jobs.start_process(
                kind="bash",
                command=[self.runtime.shell, "-lc", str(command)],
                label=_command_preview(str(command)),
            )
            return (
                f"Started background job {job.id} ({job.label}). "
                f"Use bash_output(job_id={job.id}), wait, or kill_shell to manage it."
            )

        timeout = int(arguments.get("timeout_seconds", 30))
        if timeout <= 0:
            timeout = 30

        result = _run_foreground_bash(str(command), timeout, self.sink, shell_executable=self.runtime.shell)
        output = result["output"]
        footer = f"[command] exit_code={result['exit_code']} duration_ms={result['duration_ms']} shell={self.runtime.shell}"
        if result["exit_code"] != 0:
            raise RuntimeError(f"command exited with {result['exit_code']}\n{output}\n{footer}")
        if output:
            return output.rstrip() + "\n" + footer
        return "(no output)\n" + footer


class PythonRunTool(Tool):
    def __init__(
        self,
        runtime: Optional[RuntimeSelection] = None,
        jobs: Optional[JobManager] = None,
        sink: Optional[EventSink] = None,
    ) -> None:
        self.runtime = runtime or discover_runtime(Path.cwd())
        self.jobs = jobs
        self.sink = sink or NullSink()

    @property
    def name(self) -> str:
        return "python_run"

    @property
    def description(self) -> str:
        return (
            "Run Python using the selected project runtime. This is the preferred tool for Python scripts, "
            "pytest, python -m module execution, and small Python snippets."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["file", "module", "code"],
                    "description": "file runs a project script, module runs python -m, code runs python -c",
                },
                "path": {"type": "string", "description": "Project-relative Python file for mode=file"},
                "module": {"type": "string", "description": "Module name for mode=module, such as pytest"},
                "code": {"type": "string", "description": "Python code for mode=code"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments passed after the file/module/code",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run detached and return a job id. Use bash_output, wait, or kill_shell to manage it.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum seconds to wait before terminating foreground execution",
                    "minimum": 1,
                },
            },
            "required": ["mode"],
        }

    def execute(self, arguments: JsonObject) -> str:
        command = self._command(arguments)
        label = _command_preview(command)
        if arguments.get("run_in_background"):
            if self.jobs is None:
                raise ValueError("background jobs are not available")
            job = self.jobs.start_process(kind="python", command=command, label=label, env=_headless_python_env())
            return (
                f"Started background python job {job.id} ({job.label}). "
                f"Use bash_output(job_id={job.id}), wait, or kill_shell to manage it."
            )

        timeout = int(arguments.get("timeout_seconds", 30))
        if timeout <= 0:
            timeout = 30
        result = _run_foreground_process(command, timeout, self.sink, kind="python", env=_headless_python_env())
        output = result["output"]
        footer = (
            f"[python] exit_code={result['exit_code']} duration_ms={result['duration_ms']} "
            f"executable={self.runtime.python} source={self.runtime.python_source}"
        )
        if result["exit_code"] != 0:
            raise RuntimeError(f"python exited with {result['exit_code']}\n{output}\n{footer}")
        if output:
            return output.rstrip() + "\n" + footer
        return "(no output)\n" + footer

    def _command(self, arguments: JsonObject) -> list[str]:
        mode = str(arguments.get("mode") or "")
        args = [str(item) for item in arguments.get("args", [])]
        python = self.runtime.python
        if mode == "code":
            code = str(arguments.get("code") or "")
            if not code:
                raise ValueError("code is required for mode=code")
            return [python, "-c", code, *args]
        if mode == "module":
            module = str(arguments.get("module") or "")
            if not module:
                raise ValueError("module is required for mode=module")
            return [python, "-m", module, *args]
        if mode == "file":
            raw_path = str(arguments.get("path") or "")
            if not raw_path:
                raise ValueError("path is required for mode=file")
            file_path = Path(raw_path).expanduser()
            root = Path.cwd().resolve()
            if file_path.is_absolute():
                resolved = file_path.resolve()
            else:
                resolved = (root / file_path).resolve()
            if not _is_within(root, resolved):
                raise ValueError(f"python file must be inside project: {resolved}")
            file_arg = str(resolved)
            return [python, file_arg, *args]
        raise ValueError("mode must be one of: file, module, code")


class BashOutputTool(Tool):
    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs

    @property
    def name(self) -> str:
        return "bash_output"

    @property
    def description(self) -> str:
        return "Read new output from a background bash job without blocking."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Background job id, such as bash-1"},
            },
            "required": ["job_id"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        job_id = arguments.get("job_id")
        if not job_id:
            raise ValueError("job_id is required")
        output, status = self.jobs.output(str(job_id))
        if output.strip():
            return f"[{job_id}] {status}\n{output.rstrip()}"
        return f"[{job_id}] {status}\n(no new output)"


class WaitTool(Tool):
    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs

    @property
    def name(self) -> str:
        return "wait"

    @property
    def description(self) -> str:
        return "Wait for background jobs to finish, or until timeout_seconds elapses."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "job_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional job ids. Omit to wait for all running jobs.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Optional maximum seconds to wait before returning current progress.",
                    "minimum": 1,
                },
            },
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        return self.jobs.wait(
            job_ids=arguments.get("job_ids"),
            timeout_seconds=arguments.get("timeout_seconds"),
        )


class KillShellTool(Tool):
    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs

    @property
    def name(self) -> str:
        return "kill_shell"

    @property
    def description(self) -> str:
        return "Terminate a running background bash job."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Background job id to terminate"},
            },
            "required": ["job_id"],
        }

    def execute(self, arguments: JsonObject) -> str:
        job_id = arguments.get("job_id")
        if not job_id:
            raise ValueError("job_id is required")
        return self.jobs.kill(str(job_id))


def default_registry(
    jobs: Optional[JobManager] = None,
    memory_store: Optional[AutoMemoryStore] = None,
    sink: Optional[EventSink] = None,
    job_log_dir: str | Path = ".jobs",
    git_baseline_path: str | Path = ".gitstate/baseline.json",
    runtime_selection: Optional[RuntimeSelection] = None,
    skill_store: Optional[SkillStore] = None,
    skill_runner: Optional[SubagentRunner] = None,
    task_runner: Optional[TaskRunner] = None,
    subagent_manager=None,
    attachment_store=None,
    attachment_session_id: str = "",
) -> ToolRegistry:
    jobs = jobs or JobManager(log_dir=job_log_dir, sink=sink)
    if sink is not None:
        jobs.sink = sink
    registry = ToolRegistry()
    registry.add(EchoTool())
    registry.add(ReadFileTool())
    registry.add(ListDirTool())
    registry.add(GlobTool())
    registry.add(GrepTool())
    registry.add(EditFileTool())
    registry.add(WriteFileTool())
    registry.add(BashTool(jobs, sink=sink, runtime=runtime_selection))
    registry.add(PythonRunTool(runtime=runtime_selection, jobs=jobs, sink=sink))
    registry.add(BashOutputTool(jobs))
    registry.add(WaitTool(jobs))
    registry.add(KillShellTool(jobs))
    registry.add(GitStatusTool())
    registry.add(GitDiffTool())
    registry.add(GitBaselineTool(baseline_path=git_baseline_path))
    registry.add(GitClassifyChangesTool(baseline_path=git_baseline_path))
    registry.add(GitCommitTool(baseline_path=git_baseline_path, sink=sink))
    registry.add(TodoWriteTool())
    registry.add(CompleteStepTool())
    if attachment_store is not None and attachment_session_id:
        registry.add(ListAttachmentsTool(attachment_store, attachment_session_id))
        registry.add(ReadAttachmentTool(attachment_store, attachment_session_id))
    if task_runner is not None:
        registry.add(TaskTool(task_runner))
    if subagent_manager is not None:
        from mini_agent_lab.tool.subagent_tools import (
            CancelSubagentTool,
            SubagentOutputTool,
            SubagentStatusTool,
            WaitSubagentTool,
        )

        registry.add(SubagentStatusTool(subagent_manager))
        registry.add(SubagentOutputTool(subagent_manager))
        registry.add(WaitSubagentTool(subagent_manager))
        registry.add(CancelSubagentTool(subagent_manager))
    if memory_store is not None:
        registry.add(RememberTool(memory_store))
        registry.add(ListMemoryTool(memory_store))
    if skill_store is not None:
        registry.add(ListSkillsTool(skill_store))
        registry.add(ReadSkillTool(skill_store))
        registry.add(RunSkillTool(skill_store, skill_runner))
        registry.add(InstallSkillTool(skill_store))
    # Web search tools (always available, read-only)
    from mini_agent_lab.tool.web_tools import OfficialDocsSearchTool, WebSearchTool

    registry.add(WebSearchTool())
    registry.add(OfficialDocsSearchTool())
    return registry


def pretty_schemas(registry: ToolRegistry) -> str:
    return json.dumps(registry.schemas(), ensure_ascii=False, indent=2)


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return True


def _run_foreground_bash(command: str, timeout: int, sink: EventSink, shell_executable: str = "/bin/zsh") -> dict:
    return _run_foreground_process(
        [shell_executable, "-lc", command],
        timeout,
        sink,
        kind="bash",
        display_command=command,
    )


def _run_foreground_process(
    command: str | Sequence[str],
    timeout: int,
    sink: EventSink,
    kind: str,
    shell: bool = False,
    display_command: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> dict:
    started_at = time.time()
    workspace_before = snapshot_workspace(Path.cwd())
    proc = subprocess.Popen(
        command,
        shell=shell,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        env=env,
    )
    command_id = f"cmd-{int(started_at * 1000)}-{proc.pid}"
    command_text = _command_preview(display_command or command)
    sink.emit(
        Event(
            "command_started",
            {
                "command_id": command_id,
                "kind": kind,
                "command": command_text,
                "pid": proc.pid,
                "timeout_seconds": timeout,
            },
        )
    )

    lines: list[str] = []
    lock = threading.Lock()

    def read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                lines.append(line)
            sink.emit(
                Event(
                    "command_output",
                    {
                        "command_id": command_id,
                        "text": line,
                    },
                )
            )

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    timed_out = False
    try:
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        exit_code = proc.wait()
    reader.join(timeout=1)

    finished_at = time.time()
    output = "".join(lines)
    duration_ms = int((finished_at - started_at) * 1000)
    sink.emit(
        Event(
            "command_finished",
            {
                "command_id": command_id,
                "kind": kind,
                "command": command_text,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "timed_out": timed_out,
                "output_preview": output[-1200:],
            },
        )
    )
    _emit_workspace_changes(sink, command_id, kind, workspace_before)
    if timed_out:
        raise RuntimeError(f"command timed out after {timeout}s\n{output}")
    return {
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "output": output,
        "command_id": command_id,
    }


def _emit_workspace_changes(sink: EventSink, command_id: str, kind: str, before) -> None:
    changes = diff_workspace(before, snapshot_workspace(Path.cwd()))
    if not changes:
        return
    sink.emit(
        Event(
            "workspace_changes_detected",
            {
                "source_kind": kind,
                "command_id": command_id,
                "changes": changes,
            },
        )
    )


def _command_preview(command: str | Sequence[str]) -> str:
    if isinstance(command, str):
        text = command
    else:
        text = " ".join(str(part) for part in command)
    return " ".join(text.strip().split())


def _is_within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _workspace_glob(pattern: str) -> str:
    path = Path(pattern).expanduser()
    if not path.is_absolute():
        return pattern
    root = Path.cwd().resolve()
    resolved = path.resolve()
    if not _is_within(root, resolved):
        raise ValueError(f"path_glob must be inside project: {resolved}")
    rel = resolved.relative_to(root)
    return str(rel) or "."


def _headless_python_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("TK_SILENCE_DEPRECATION", "1")
    return env
