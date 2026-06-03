from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

from mini_agent_lab.events import Event, EventSink, NullSink

if TYPE_CHECKING:
    from mini_agent_lab.auto_review import AutoReviewAgent, Decision as ReviewDecision, ReviewInput


Decision = Literal["allow", "ask", "deny"]
PermissionMode = Literal["default", "auto_review", "full_access"]


@dataclass(frozen=True)
class SafetyResult:
    decision: Decision
    reason: str


def _decision(value: Any, fallback: Decision = "ask") -> Decision:
    if value in {"allow", "ask", "deny"}:
        return value
    return fallback


class PolicyConfig:
    """User-editable safety policy loaded from mcode-policy.json."""

    def __init__(self, raw: dict[str, Any], root_dir: Optional[Path] = None) -> None:
        self.raw = raw
        self.root_dir = root_dir or Path.cwd()
        self.read_only_default = _decision(raw.get("read_only_default"), "allow")
        self.unknown_write_default = _decision(raw.get("unknown_write_default"), "ask")
        self.tool_overrides = raw.get("tool_overrides", {})
        self.write_tools = set(raw.get("write_tools", ["write_file", "edit_file"]))
        self.write_policy = raw.get("write_policy", {})
        self.protected_write_prefixes = [
            _resolve_path(p, self.root_dir) for p in raw.get("protected_write_prefixes", [])
        ]
        self.protected_write_exact = [
            _resolve_path(p, self.root_dir) for p in raw.get("protected_write_exact", [])
        ]
        self.workspace_root = _resolve_path(raw.get("workspace_root", "."), self.root_dir)
        self.bash_policy = raw.get("bash_policy", {})

    @classmethod
    def load(cls, path: Optional[str] = None) -> "PolicyConfig":
        policy_path = _policy_path(path)
        root_dir = policy_path.parent if policy_path.parent != Path("") else Path.cwd()
        if not policy_path.exists():
            return cls({}, root_dir=Path.cwd())
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        return cls(raw, root_dir=root_dir.resolve())


class SafetyGate:
    """Risk gate for tool execution.

    Default policy:
    - read-only tools are allowed.
    - write_file/edit_file inside workspace are allowed.
    - write_file/edit_file outside workspace ask.
    - protected paths and clearly dangerous bash commands are denied.
    - other non-read-only tools ask.
    """

    def __init__(
        self,
        policy: Optional[PolicyConfig] = None,
        permission_mode: PermissionMode = "auto_review",
        auto_review_agent: Optional[Any] = None,
    ) -> None:
        self.policy = policy or PolicyConfig.load()
        self.permission_mode: PermissionMode = (
            permission_mode if permission_mode in {"default", "auto_review", "full_access"} else "auto_review"
        )
        self.auto_review_agent = auto_review_agent

    def review_ask(
        self,
        tool_name: str,
        arguments: dict,
        safety_reason: str,
        user_message: str = "",
        session_summary: str = "",
        plan_mode: bool = False,
    ) -> tuple[str, str]:
        """Use AutoReviewAgent to resolve an "ask" decision.

        Returns (decision, reason) where decision is "approve", "reject", or "escalate".
        If no auto_review_agent is configured, returns ("escalate", "no reviewer").
        """
        if self.auto_review_agent is None:
            return ("escalate", "no auto-review agent configured")

        from mini_agent_lab.auto_review import ReviewInput

        result = self.auto_review_agent.review(ReviewInput(
            user_message=user_message,
            tool_name=tool_name,
            tool_args=arguments,
            safety_reason=safety_reason,
            session_summary=session_summary,
            plan_mode=plan_mode,
        ))
        return (result.decision.value, result.reason)

    def check(self, tool_name: str, arguments: dict, read_only: bool) -> SafetyResult:
        override = self.policy.tool_overrides.get(tool_name)
        if override:
            decision = _decision(override, "ask")
            return SafetyResult(decision, f"tool override: {tool_name} -> {decision}")

        if tool_name == "bash":
            return self._check_bash(arguments)

        if tool_name == "python_run":
            if self.permission_mode == "full_access":
                return SafetyResult("allow", "full access mode allows python_run in the selected project runtime")
            mode = str(arguments.get("mode", ""))
            target = arguments.get("path") or arguments.get("module") or "inline code"
            return SafetyResult(
                "ask",
                f"python_run will execute Python ({mode}: {target}) in the selected project runtime.",
            )

        if tool_name == "git_commit":
            return SafetyResult(
                "ask",
                "git_commit 会创建一次本地提交。它不会上传到远程仓库，但会改变本地项目历史。"
                "工具只会提交指定文件，不会执行 git add .。如果你不确定，建议拒绝。",
            )

        if tool_name in {"task", "run_skill"}:
            return SafetyResult(
                "allow",
                f"{tool_name} delegates work through the agent loop; child tool calls are checked separately",
            )

        if tool_name == "cancel_subagent":
            return SafetyResult("allow", "cancel_subagent only requests cooperative cancellation")

        if tool_name in self.policy.write_tools:
            return self._check_write_tool(tool_name, arguments)

        if read_only:
            return SafetyResult(self.policy.read_only_default, "read-only tool")

        if self.permission_mode == "full_access":
            return SafetyResult("allow", f"full access mode allows {tool_name}; extreme-risk commands are still denied")
        return SafetyResult(self.policy.unknown_write_default, f"{tool_name} may change files or system state")

    def _check_write_tool(self, tool_name: str, arguments: dict) -> SafetyResult:
        path = arguments.get("path")
        if not path:
            return SafetyResult("deny", f"{tool_name} has no path argument")
        target = _resolve_path(str(path), Path.cwd())

        if self._is_protected(target):
            decision = _decision(self.policy.write_policy.get("protected"), "deny")
            return SafetyResult(decision, f"{tool_name} targets protected path: {target}")

        if _is_within(self.policy.workspace_root, target):
            decision = _decision(self.policy.write_policy.get("inside_workspace"), "allow")
            return SafetyResult(decision, f"{tool_name} targets workspace path: {target}")

        if self.permission_mode == "full_access":
            return SafetyResult("allow", f"full access mode allows {tool_name} outside workspace: {target}")

        decision = _decision(self.policy.write_policy.get("outside_workspace"), "ask")
        return SafetyResult(decision, f"{tool_name} targets outside workspace: {target}")

    def _check_bash(self, arguments: dict) -> SafetyResult:
        command = str(arguments.get("command", ""))
        normalized = " ".join(command.strip().split()).lower()
        extreme = _extreme_bash_reason(normalized)
        if extreme:
            return SafetyResult("deny", extreme)

        # Tier 2: escalate (human approval required) — check first
        for item in self.policy.bash_policy.get("escalate_patterns", []):
            pattern = item.get("pattern", "")
            if pattern and re.search(pattern, command):
                return SafetyResult("ask", f"高风险命令: {item.get('reason', '')}")

        # Tier 0: auto-allow (safe commands) — check second
        for item in self.policy.bash_policy.get("auto_allow_patterns", []):
            pattern = item.get("pattern", "")
            if pattern and re.search(pattern, normalized):
                return SafetyResult("allow", f"安全命令: {item.get('reason', '')}")

        # git commands with special handling
        git_result = classify_git_bash_command(command)
        if git_result is not None:
            if self.permission_mode == "full_access":
                if git_result.reason.startswith("高风险"):
                    return SafetyResult("deny", git_result.reason)
                return SafetyResult("allow", "full access mode allows non-extreme git shell command")
            return git_result

        if self.permission_mode == "full_access":
            return SafetyResult("allow", "full access mode allows bash; extreme-risk commands are still denied")

        # Tier 1: auto_review (AutoReviewAgent decides)
        return SafetyResult("ask", "bash command requires safety review")

    def _is_protected(self, target: Path) -> bool:
        for exact in self.policy.protected_write_exact:
            if target == exact:
                return True
        for prefix in self.policy.protected_write_prefixes:
            if _is_within(prefix, target):
                return True
        return False


class Approver:
    def __init__(self, sink: Optional[EventSink] = None) -> None:
        self.sink = sink or NullSink()

    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        self.sink.emit(
            Event(
                "safety_ask",
                {"tool_name": tool_name, "arguments": arguments, "reason": reason},
            )
        )
        answer = input("Allow this tool call? [y/N] ").strip().lower()
        return answer in {"y", "yes"}


GIT_READ_ONLY_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "blame",
    "grep",
    "ls-files",
    "ls-tree",
    "rev-parse",
    "rev-list",
    "describe",
    "reflog",
    "shortlog",
    "whatchanged",
    "cherry",
    "cat-file",
    "for-each-ref",
    "name-rev",
}

GIT_WRITE_ASK_SUBCOMMANDS = {
    "add",
    "commit",
    "push",
    "stash",
    "reset",
    "restore",
    "checkout",
    "switch",
    "branch",
    "merge",
    "rebase",
    "pull",
    "fetch",
    "clone",
    "remote",
    "config",
    "tag",
    "cherry-pick",
    "revert",
}

SHELL_SYNTAX_RE = re.compile(r"(;|\|\||&&|\||<|>|\n|`|\$\(|&)")


def classify_git_bash_command(command: str) -> Optional[SafetyResult]:
    """Return a git-specific safety decision for bash commands, or None."""
    stripped = command.strip()
    if not stripped or not re.match(r"(?i)^git(\s|$)", stripped):
        return None

    lowered = " ".join(stripped.lower().split())
    danger = _dangerous_git_reason(lowered)
    if danger:
        return SafetyResult("ask", danger)

    if SHELL_SYNTAX_RE.search(stripped):
        return SafetyResult(
            "ask",
            "这个 git 命令里包含 shell 组合语法，可能不只是执行 git。"
            "如果你不确定它会做什么，建议拒绝。",
        )

    try:
        parts = shlex.split(stripped)
    except ValueError:
        return SafetyResult("ask", "无法安全解析这个 git 命令。如果你不确定，建议拒绝。")
    if not parts or parts[0].lower() != "git":
        return None
    if len(parts) == 1:
        return SafetyResult("ask", "git command without subcommand requires approval")

    subcmd = parts[1].lower()
    args = [part.lower() for part in parts[2:]]
    if subcmd in GIT_READ_ONLY_SUBCOMMANDS and not _git_readonly_args_are_unsafe(subcmd, args):
        return SafetyResult("allow", f"git {subcmd} is read-only")
    if subcmd in GIT_READ_ONLY_SUBCOMMANDS:
        return SafetyResult(
            "ask",
            "这个 git 查看命令带有可能写入文件的参数。"
            "它可能会在本地生成或覆盖文件。如果你不确定，建议拒绝。",
        )
    if subcmd in GIT_WRITE_ASK_SUBCOMMANDS:
        return SafetyResult("ask", _git_human_approval_reason(subcmd))
    return SafetyResult("ask", f"这是一个未识别的 git 子命令：{subcmd}。如果你不确定它会做什么，建议拒绝。")


def _dangerous_git_reason(lowered: str) -> str:
    if re.search(r"^git\s+push\b.*(--force\b|-f\b|--mirror\b|--delete\b)", lowered):
        return "高风险：这个 git push 可能覆盖远程历史或删除远程分支。如果你不确定，建议拒绝。"
    if re.search(r"^git\s+reset\b.*--hard\b", lowered):
        return "高风险：git reset --hard 可能丢弃本地未保存改动。如果你不确定，建议拒绝。"
    if re.search(r"^git\s+clean\b.*\s-[^\s]*f", lowered):
        return "高风险：git clean -f 会删除未跟踪文件，可能造成数据丢失。如果你不确定，建议拒绝。"
    if re.search(r"^git\s+checkout\b.*--\s+\.$", lowered):
        return "高风险：git checkout -- . 可能丢弃当前目录里的本地改动。如果你不确定，建议拒绝。"
    if lowered == "git restore ." or re.search(r"^git\s+restore\b.*\s\.$", lowered):
        return "高风险：git restore . 可能丢弃当前目录里的本地改动。如果你不确定，建议拒绝。"
    return ""


def _git_readonly_args_are_unsafe(subcmd: str, args: list[str]) -> bool:
    if subcmd in {"diff", "show", "log"}:
        return any(arg == "--output" or arg.startswith("--output=") for arg in args)
    return False


def _git_human_approval_reason(subcmd: str) -> str:
    reasons = {
        "add": (
            "git add 会把文件加入下一次提交的范围。"
            "它不会直接改文件内容，但会影响之后 commit 包含哪些改动。"
            "如果你不确定，建议拒绝。"
        ),
        "commit": (
            "git commit 会把当前已暂存的本地改动保存成一次提交。"
            "它不会上传到远程仓库，但会改变本地项目历史。"
            "如果你不确定，建议拒绝。"
        ),
        "push": (
            "git push 会把本地提交上传到远程仓库，别人可能会看到这些改动。"
            "如果你不确定，建议拒绝。"
        ),
        "stash": (
            "git stash 会把当前未提交改动临时收起来，让工作区变干净。"
            "改动通常还能找回，但初学者容易找不到。"
            "如果你不确定，建议拒绝。"
        ),
        "reset": (
            "git reset 会移动提交指针或改变暂存区。"
            "某些形式可能让改动从当前视图里消失。"
            "如果你不确定，建议拒绝。"
        ),
        "restore": (
            "git restore 会恢复文件内容或暂存状态。"
            "用错时可能让你当前看到的本地改动消失。"
            "如果你不确定，建议拒绝。"
        ),
        "checkout": (
            "git checkout 可能切换分支或恢复文件。"
            "它可能改变你当前看到的文件内容。"
            "如果你不确定，建议拒绝。"
        ),
        "switch": (
            "git switch 会切换分支，可能改变当前工作区显示的代码。"
            "如果你不确定，建议拒绝。"
        ),
        "fetch": (
            "git fetch 会连接远程仓库下载最新信息。"
            "通常不会修改当前文件，但会访问网络。"
            "如果你不确定，可以拒绝。"
        ),
        "pull": (
            "git pull 会从远程下载代码并合并到当前分支。"
            "它可能改变本地文件并产生冲突。"
            "如果你不确定，建议拒绝。"
        ),
        "clone": (
            "git clone 会从远程下载一个仓库到本地。"
            "它会访问网络并创建新目录。"
            "如果你不确定，建议拒绝。"
        ),
        "remote": (
            "git remote 会查看或修改远程仓库地址。"
            "修改远程地址可能影响之后 push/pull 的目标。"
            "如果你不确定，建议拒绝。"
        ),
        "config": (
            "git config 会读取或修改 git 配置。"
            "修改配置可能影响之后所有 git 操作。"
            "如果你不确定，建议拒绝。"
        ),
        "branch": (
            "git branch 可能创建、删除或修改分支。"
            "这会改变本地仓库结构。"
            "如果你不确定，建议拒绝。"
        ),
        "merge": (
            "git merge 会把其他分支合并到当前分支。"
            "它可能修改很多文件并产生冲突。"
            "如果你不确定，建议拒绝。"
        ),
        "rebase": (
            "git rebase 会重写本地提交排列方式。"
            "如果用错，可能让历史变复杂。"
            "如果你不确定，建议拒绝。"
        ),
        "tag": (
            "git tag 可能创建或修改版本标签。"
            "标签通常用于发布或标记版本。"
            "如果你不确定，建议拒绝。"
        ),
        "cherry-pick": (
            "git cherry-pick 会把某个提交应用到当前分支。"
            "它可能修改本地文件并产生冲突。"
            "如果你不确定，建议拒绝。"
        ),
        "revert": (
            "git revert 会创建一个新的提交来撤销旧提交。"
            "它会修改本地文件和提交历史。"
            "如果你不确定，建议拒绝。"
        ),
    }
    return reasons.get(subcmd, f"git {subcmd} 会改变仓库状态。如果你不确定，建议拒绝。")


def _extreme_bash_reason(normalized: str) -> str:
    checks = [
        (r"\brm\s+-[^\n;]*r[^\n;]*f\s+(/|~|/users(?:/[^/\s]+)?\s*$)", "极高风险：递归强制删除根目录、home 或用户目录。"),
        (r"\bsudo\b", "极高风险：sudo 命令会提升权限。"),
        (r"\bmkfs\b", "极高风险：mkfs 可能格式化磁盘。"),
        (r"\bdd\s+if=", "极高风险：dd 可能直接写入磁盘或破坏数据。"),
        (r"\b(shutdown|reboot|halt)\b", "极高风险：命令可能关闭或重启系统。"),
        (r"\b(chmod|chown)\s+-[^\n;]*r\b.*\s(/|~|/users(?:/[^/\s]+)?\s*$)", "极高风险：递归修改系统或用户目录权限。"),
    ]
    for pattern, reason in checks:
        if re.search(pattern, normalized):
            return reason
    return ""


def _resolve_path(path: str, root_dir: Path) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = root_dir / expanded
    # strict=False keeps paths that do not exist yet, which is essential for
    # write_file. Parent symlinks are still resolved where possible.
    return expanded.resolve(strict=False)


def _is_within(root: Path, target: Path) -> bool:
    root = root.resolve(strict=False)
    target = target.resolve(strict=False)
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _policy_path(path: Optional[str]) -> Path:
    if path:
        requested = Path(path)
        if requested.exists() or requested.name != "mcode-policy.json":
            return requested
        legacy = requested.with_name("mini-agent-policy.json")
        if legacy.exists():
            return legacy
        return requested
    env_path = os.environ.get("MCODE_POLICY_FILE") or os.environ.get("MINI_AGENT_POLICY_FILE")
    if env_path:
        return Path(env_path)
    default = Path("mcode-policy.json")
    legacy = Path("mini-agent-policy.json")
    return legacy if not default.exists() and legacy.exists() else default
