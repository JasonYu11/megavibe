"""Tests for git command risk classification inside the bash safety gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.safety import PolicyConfig, SafetyGate, classify_git_bash_command


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _gate() -> SafetyGate:
    return SafetyGate(
        PolicyConfig(
            {
                "bash_policy": {
                    "default": "ask",
                    "risk_patterns": [
                        {
                            "pattern": "\\bsudo\\b",
                            "reason": "high risk: sudo command",
                            "decision": "ask",
                        },
                        {
                            "pattern": "\\brm\\s+-[^\\n;]*r[^\\n;]*f\\s+/",
                            "reason": "high risk: recursive force delete from root",
                            "decision": "ask",
                        },
                    ],
                }
            }
        )
    )


def _decision(command: str) -> str:
    return _gate().check("bash", {"command": command}, read_only=False).decision


def _reason(command: str) -> str:
    return _gate().check("bash", {"command": command}, read_only=False).reason


def test_git_read_only_commands_are_allowed() -> None:
    for command in [
        "git status",
        "git diff",
        "git log --oneline",
        "git show HEAD",
        "git blame file.py",
        "git ls-files",
        "git rev-parse --show-toplevel",
    ]:
        _assert(_decision(command) == "allow", f"{command!r} is allowed")


def test_git_writers_and_remote_commands_ask() -> None:
    for command in [
        "git commit -m 'msg'",
        "git add file.py",
        "git push origin main",
        "git stash push",
        "git reset HEAD~1",
        "git restore file.py",
        "git checkout main",
        "git fetch origin",
        "git pull",
        "git clone https://example.com/repo.git",
    ]:
        _assert(_decision(command) == "ask", f"{command!r} asks")


def test_git_ask_reasons_are_human_readable() -> None:
    examples = [
        ("git commit -m 'msg'", "不会上传到远程仓库"),
        ("git push origin main", "上传到远程仓库"),
        ("git stash push", "临时收起来"),
        ("git add file.py", "下一次提交的范围"),
        ("git pull", "可能改变本地文件"),
        ("git fetch origin", "通常不会修改当前文件"),
    ]
    for command, expected in examples:
        reason = _reason(command)
        _assert(expected in reason, f"{command!r} explains: {expected}")
        _assert("如果你不确定" in reason, f"{command!r} includes unsure-user guidance")


def test_git_dangerous_commands_ask() -> None:
    for command in [
        "git push --force origin main",
        "git push -f",
        "git push --delete origin old-branch",
        "git push --mirror",
        "git reset --hard",
        "git reset --hard HEAD~1",
        "git clean -f",
        "git clean -fd",
        "git clean -xfd",
        "git checkout -- .",
        "git restore .",
    ]:
        _assert(_decision(command) == "ask", f"{command!r} asks")


def test_git_shell_syntax_is_never_auto_allowed() -> None:
    for command in [
        "git status && rm file",
        "git diff > patch.txt",
        "git status | cat",
        "git log; rm file",
        "git show $(touch output)",
    ]:
        _assert(_decision(command) == "ask", f"{command!r} asks because of shell syntax")


def test_git_shell_syntax_still_respects_global_risk_patterns() -> None:
    for command in [
        "git status && sudo reboot",
        "git status; rm -rf /",
    ]:
        _assert(_decision(command) == "deny", f"{command!r} is denied as extreme risk")


def test_git_readonly_output_args_are_not_auto_allowed() -> None:
    for command in [
        "git diff --output changes.patch",
        "git show --output=changes.patch HEAD",
        "git log --output changes.patch",
    ]:
        _assert(_decision(command) == "ask", f"{command!r} asks because it writes output")
        _assert("可能写入文件" in _reason(command), f"{command!r} explains output risk")


def test_non_git_commands_are_not_classified_as_git() -> None:
    _assert(classify_git_bash_command("printf ok") is None, "non-git command returns None")
    _assert(_decision("printf ok") == "ask", "non-git bash still follows bash default")


if __name__ == "__main__":
    test_git_read_only_commands_are_allowed()
    test_git_writers_and_remote_commands_ask()
    test_git_ask_reasons_are_human_readable()
    test_git_dangerous_commands_ask()
    test_git_shell_syntax_is_never_auto_allowed()
    test_git_shell_syntax_still_respects_global_risk_patterns()
    test_git_readonly_output_args_are_not_auto_allowed()
    test_non_git_commands_are_not_classified_as_git()
    print("All git command safety tests passed.")
