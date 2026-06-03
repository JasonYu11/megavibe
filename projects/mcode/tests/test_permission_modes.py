"""Tests for UI-selectable permission modes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.safety import PolicyConfig, SafetyGate


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _gate(mode: str) -> SafetyGate:
    return SafetyGate(PolicyConfig({"bash_policy": {"default": "ask"}}), permission_mode=mode)  # type: ignore[arg-type]


def test_default_and_auto_review_keep_execution_approval() -> None:
    for mode in ["default", "auto_review"]:
        gate = _gate(mode)
        _assert(gate.check("bash", {"command": "printf ok"}, read_only=False).decision == "ask", f"{mode} asks for bash")
        _assert(
            gate.check("python_run", {"mode": "code", "code": "print('ok')"}, read_only=False).decision == "ask",
            f"{mode} asks for python_run",
        )


def test_full_access_allows_normal_execution() -> None:
    gate = _gate("full_access")
    _assert(gate.check("bash", {"command": "printf ok"}, read_only=False).decision == "allow", "full access allows simple bash")
    _assert(
        gate.check("python_run", {"mode": "code", "code": "print('ok')"}, read_only=False).decision == "allow",
        "full access allows python_run",
    )
    _assert(
        gate.check("custom_write_tool", {"value": "ok"}, read_only=False).decision == "allow",
        "full access allows unknown non-read-only tools",
    )


def test_full_access_still_denies_extreme_risk() -> None:
    gate = _gate("full_access")
    for command in [
        "sudo ls",
        "rm -rf /",
        "reboot",
        "mkfs /dev/disk9",
        "dd if=/dev/zero of=/dev/disk9",
        "chmod -R 777 /",
        "git reset --hard",
        "git clean -fd",
        "git push --force origin main",
    ]:
        result = gate.check("bash", {"command": command}, read_only=False)
        _assert(result.decision == "deny", f"full access denies {command!r}")


if __name__ == "__main__":
    test_default_and_auto_review_keep_execution_approval()
    test_full_access_allows_normal_execution()
    test_full_access_still_denies_extreme_risk()
    print("All permission mode tests passed.")
