from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("MCODE_RUNTIME_ROOT", "")).expanduser() if os.environ.get("MCODE_RUNTIME_ROOT") else BACKEND_ROOT.parents[1]
APP_DATA_DIR = Path(os.environ.get("MCODE_APP_DATA_DIR", "")).expanduser() if os.environ.get("MCODE_APP_DATA_DIR") else REPO_ROOT / ".mcode-ui"
APP_ENV_PATH = APP_DATA_DIR / ".env"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.provider import DeepSeekProvider, Message, ProviderError
import keychain


CONFIG_FILE = "mcode-config.json"
POLICY_FILE = "mcode-policy.json"


def read_project_settings(root: Path) -> dict[str, Any]:
    config = load_app_config(root / CONFIG_FILE)
    prime_settings_env(root)
    policy = _read_policy(root)
    return {
        "provider": config.provider.__dict__,
        "agent": config.agent.__dict__,
        "context": config.context.__dict__,
        "paths": {
            **config.paths.__dict__,
            "skill_custom_dirs": list(config.paths.skill_custom_dirs),
        },
        "runtime": config.runtime.__dict__,
        "ui": config.ui.__dict__,
        "auto_review": policy.get("auto_review", {}),
        "api_key_configured": _api_key_configured(),
    }


def write_project_settings(root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    path = root / CONFIG_FILE
    raw: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))

    for section in ("provider", "agent", "context", "paths", "runtime", "ui"):
        if section not in patch:
            continue
        value = patch.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"{section} must be an object")
        current = raw.get(section, {})
        raw[section] = {**(current if isinstance(current, dict) else {}), **_clean_section(section, value)}

    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Handle auto_review in policy file separately
    if "auto_review" in patch:
        ar = patch["auto_review"]
        if isinstance(ar, dict):
            _write_policy_auto_review(root, ar)

    return read_project_settings(root)


def read_policy_settings(root: Path) -> dict[str, Any]:
    """Read the full mcode-policy.json for UI editing."""
    return _read_policy(root)


def write_policy_settings(root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Write mcode-policy.json, merging with existing."""
    policy = _read_policy(root)
    # Deep merge the auto_review section
    if "auto_review" in patch and isinstance(patch["auto_review"], dict):
        ar = patch["auto_review"]
        current = policy.get("auto_review", {})
        if isinstance(current, dict):
            policy["auto_review"] = {**current, **ar}
        else:
            policy["auto_review"] = ar

    policy_path = root / POLICY_FILE
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _read_policy(root)


def _read_policy(root: Path) -> dict[str, Any]:
    """Read mcode-policy.json, returning {} if not found."""
    policy_path = root / POLICY_FILE
    if policy_path.exists():
        return json.loads(policy_path.read_text(encoding="utf-8"))
    return {}


def _write_policy_auto_review(root: Path, ar: dict) -> None:
    """Write only the auto_review section of the policy file."""
    policy = _read_policy(root)
    policy["auto_review"] = ar
    policy_path = root / POLICY_FILE
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_api_key(value: str) -> dict[str, Any]:
    api_key = value.strip()
    if not api_key or api_key == "sk-your-key-here":
        raise ValueError("API key cannot be empty")
    try:
        keychain.write_api_key(api_key)
        _write_env_value(APP_ENV_PATH, "DEEPSEEK_API_KEY", None)
    except Exception:
        _write_env_value(APP_ENV_PATH, "DEEPSEEK_API_KEY", api_key)
    os.environ["DEEPSEEK_API_KEY"] = api_key
    return {"api_key_configured": True}


def clear_api_key() -> dict[str, Any]:
    keychain.delete_api_key()
    _write_env_value(APP_ENV_PATH, "DEEPSEEK_API_KEY", None)
    if os.environ.get("DEEPSEEK_API_KEY"):
        os.environ.pop("DEEPSEEK_API_KEY", None)
    return {"api_key_configured": _api_key_configured()}


def run_api_test(root: Path, count: int = 3) -> dict[str, Any]:
    prime_settings_env(root)
    cfg = load_config()
    settings = read_project_settings(root)
    provider_cfg = settings["provider"]
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=str(provider_cfg["base_url"]),
        model=str(provider_cfg["model"]),
        temperature=0.0,
        thinking_mode=bool(provider_cfg.get("thinking_mode", False)),
        timeout_seconds=float(provider_cfg["timeout_seconds"]),
        max_retries=int(provider_cfg["max_retries"]),
        proxy_url=str(provider_cfg.get("proxy_url") or ""),
        trust_env=bool(provider_cfg.get("trust_env", False)),
    )
    results = [_call_once(provider, index + 1) for index in range(max(1, min(count, 10)))]
    return {"summary": _summary(results), "results": results}


def _call_once(provider: DeepSeekProvider, index: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = provider.complete(
            [
                Message(role="system", content="You are a terse API health-check responder."),
                Message(role="user", content="Reply with exactly: ok"),
            ],
            max_tokens=16,
        )
        return {
            "index": index,
            "ok": True,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "model": response.raw_model,
            "content_preview": (response.content or "")[:120],
            "error_kind": "",
            "error": "",
            "status_code": None,
            "retryable": False,
            "request_id": "",
        }
    except Exception as exc:
        provider_error = exc if isinstance(exc, ProviderError) else None
        return {
            "index": index,
            "ok": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "model": "",
            "content_preview": "",
            "error_kind": provider_error.kind if provider_error else type(exc).__name__,
            "error": str(exc),
            "status_code": provider_error.status_code if provider_error else None,
            "retryable": provider_error.retryable if provider_error else False,
            "request_id": provider_error.request_id if provider_error else "",
        }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item["elapsed_seconds"]) for item in results if item["ok"]]
    errors: dict[str, int] = {}
    for item in results:
        if not item["ok"]:
            kind = str(item["error_kind"] or "unknown")
            errors[kind] = errors.get(kind, 0) + 1
    summary: dict[str, Any] = {
        "total": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "errors": errors,
    }
    if latencies:
        sorted_latencies = sorted(latencies)
        summary.update(
            {
                "min_seconds": min(latencies),
                "median_seconds": round(statistics.median(latencies), 3),
                "p95_seconds": sorted_latencies[min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))],
                "max_seconds": max(latencies),
            }
        )
    return summary


def _api_key_configured() -> bool:
    value = os.environ.get("DEEPSEEK_API_KEY", "")
    return bool(value and value != "sk-your-key-here")


def prime_settings_env(root: Path) -> None:
    keychain_value = keychain.read_api_key()
    if keychain_value and keychain_value != "sk-your-key-here":
        os.environ["DEEPSEEK_API_KEY"] = keychain_value
    load_dotenv(APP_ENV_PATH)
    load_dotenv(REPO_ROOT / ".env")
    project_env = root / ".env"
    if project_env.resolve(strict=False) == APP_ENV_PATH.resolve(strict=False):
        return
    _load_env_file(project_env, override=True)


def _load_env_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "DEEPSEEK_API_KEY" and value == "sk-your-key-here" and os.environ.get(key):
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def _write_env_value(path: Path, key: str, value: str | None) -> None:
    entries: list[tuple[str | None, str]] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                entries.append((None, raw))
                continue
            current_key, _ = stripped.split("=", 1)
            if current_key.strip() == key:
                continue
            entries.append((current_key.strip(), raw))
    if value is not None:
        entries.append((key, f"{key}={value}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line for _, line in entries).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _clean_section(section: str, value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "provider": {"base_url", "model", "thinking_mode", "temperature", "timeout_seconds", "max_retries", "proxy_url", "trust_env"},
        "agent": {"max_steps"},
        "context": {
            "context_window_tokens",
            "compact_ratio",
            "chars_per_token",
            "recent_keep",
            "auto_compact",
            "summary_mode",
            "target_summary_ratio",
            "min_summary_tokens",
            "max_summary_tokens",
        },
        "paths": {
            "session_dir",
            "run_dir",
            "job_dir",
            "gitstate_dir",
            "checkpoint_dir",
            "archive_dir",
            "memory_dir",
            "subagent_dir",
            "policy_file",
            "skill_custom_dirs",
        },
        "runtime": {"shell", "python", "python_preference"},
        "ui": {"language", "theme", "file_open_app", "show_thought_summary"},
    }[section]
    cleaned = {key: value[key] for key in allowed if key in value}
    if section == "provider":
        if "base_url" in cleaned:
            cleaned["base_url"] = str(cleaned["base_url"]).rstrip("/")
        if "model" in cleaned:
            cleaned["model"] = str(cleaned["model"])
        if "thinking_mode" in cleaned:
            cleaned["thinking_mode"] = bool(cleaned["thinking_mode"])
        for key in ("temperature", "timeout_seconds"):
            if key in cleaned:
                cleaned[key] = float(cleaned[key])
        if "max_retries" in cleaned:
            cleaned["max_retries"] = int(cleaned["max_retries"])
        if "proxy_url" in cleaned:
            cleaned["proxy_url"] = str(cleaned["proxy_url"])
        if "trust_env" in cleaned:
            cleaned["trust_env"] = bool(cleaned["trust_env"])
    if section == "agent" and "max_steps" in cleaned:
        cleaned["max_steps"] = int(cleaned["max_steps"])
    if section == "ui":
        if "file_open_app" in cleaned:
            cleaned["file_open_app"] = str(cleaned["file_open_app"])
        if "show_thought_summary" in cleaned:
            cleaned["show_thought_summary"] = bool(cleaned["show_thought_summary"])
    return cleaned
