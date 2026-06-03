from __future__ import annotations

import subprocess


SERVICE = "local.mcode.app"
ACCOUNT = "DEEPSEEK_API_KEY"


def available() -> bool:
    return _run(["/usr/bin/security", "help"]).returncode == 0


def read_api_key() -> str:
    result = _run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def write_api_key(value: str) -> None:
    delete_api_key()
    result = _run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE,
            "-a",
            ACCOUNT,
            "-w",
            value,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to write API key to Keychain")


def delete_api_key() -> None:
    _run(["/usr/bin/security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT])


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
