from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    thinking_mode: bool = False
    temperature: float = 0.2
    timeout_seconds: float = 30.0
    max_retries: int = 4
    proxy_url: str = ""
    trust_env: bool = False


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 300


@dataclass(frozen=True)
class UiConfig:
    language: str = "zh"
    theme: str = "system"
    file_open_app: str = "cursor"
    show_thought_summary: bool = True


@dataclass(frozen=True)
class ContextConfig:
    context_window_tokens: int = 200000
    compact_ratio: float = 0.75
    chars_per_token: int = 3
    recent_keep: int = 12
    auto_compact: bool = True
    summary_mode: str = "llm"
    target_summary_ratio: float = 0.1
    min_summary_tokens: int = 10000
    max_summary_tokens: int = 20000

    @property
    def trigger_chars(self) -> int:
        return int(self.context_window_tokens * self.compact_ratio * self.chars_per_token)


@dataclass(frozen=True)
class PathConfig:
    session_dir: str = ".sessions"
    run_dir: str = ".runs"
    job_dir: str = ".jobs"
    gitstate_dir: str = ".gitstate"
    checkpoint_dir: str = ".checkpoints"
    archive_dir: str = ".archives"
    memory_dir: str = ".memory"
    subagent_dir: str = ".subagents"
    policy_file: str = "mcode-policy.json"
    skill_custom_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeConfig:
    shell: str = "/bin/zsh"
    python: str = ""
    python_preference: str = "conda"


@dataclass(frozen=True)
class AppConfig:
    provider: ProviderConfig
    agent: AgentConfig
    context: ContextConfig
    paths: PathConfig
    runtime: RuntimeConfig
    ui: UiConfig


def load_app_config(path: Optional[str] = None) -> AppConfig:
    config_path = _config_path(path)
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    provider_raw = raw.get("provider", {})
    agent_raw = raw.get("agent", {})
    context_raw = raw.get("context", {})
    paths_raw = raw.get("paths", {})
    runtime_raw = raw.get("runtime", {})
    ui_raw = raw.get("ui", {})
    return AppConfig(
        provider=ProviderConfig(
            base_url=str(provider_raw.get("base_url", os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))),
            model=str(provider_raw.get("model", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))),
            thinking_mode=_coerce_bool(provider_raw.get("thinking_mode", os.environ.get("DEEPSEEK_THINKING_MODE", "false"))),
            temperature=float(provider_raw.get("temperature", _env("MCODE_TEMPERATURE", "MINI_AGENT_TEMPERATURE", "0.2"))),
            timeout_seconds=float(provider_raw.get("timeout_seconds", os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "30"))),
            max_retries=int(provider_raw.get("max_retries", os.environ.get("DEEPSEEK_MAX_RETRIES", "4"))),
            proxy_url=str(provider_raw.get("proxy_url", os.environ.get("DEEPSEEK_PROXY_URL", ""))),
            trust_env=_coerce_bool(provider_raw.get("trust_env", os.environ.get("DEEPSEEK_TRUST_ENV", "false"))),
        ),
        agent=AgentConfig(
            max_steps=int(agent_raw.get("max_steps", _env("MCODE_MAX_STEPS", "MINI_AGENT_MAX_STEPS", "300"))),
        ),
        context=ContextConfig(
            context_window_tokens=int(context_raw.get("context_window_tokens", 200000)),
            compact_ratio=float(context_raw.get("compact_ratio", 0.75)),
            chars_per_token=int(context_raw.get("chars_per_token", 3)),
            recent_keep=int(context_raw.get("recent_keep", 12)),
            auto_compact=bool(context_raw.get("auto_compact", True)),
            summary_mode=str(context_raw.get("summary_mode", "llm")),
            target_summary_ratio=float(context_raw.get("target_summary_ratio", 0.1)),
            min_summary_tokens=int(context_raw.get("min_summary_tokens", 10000)),
            max_summary_tokens=int(context_raw.get("max_summary_tokens", 20000)),
        ),
        paths=PathConfig(
            session_dir=str(paths_raw.get("session_dir", ".sessions")),
            run_dir=str(paths_raw.get("run_dir", ".runs")),
            job_dir=str(paths_raw.get("job_dir", ".jobs")),
            gitstate_dir=str(paths_raw.get("gitstate_dir", ".gitstate")),
            checkpoint_dir=str(paths_raw.get("checkpoint_dir", ".checkpoints")),
            archive_dir=str(paths_raw.get("archive_dir", ".archives")),
            memory_dir=str(paths_raw.get("memory_dir", ".memory")),
            subagent_dir=str(paths_raw.get("subagent_dir", ".subagents")),
            policy_file=str(paths_raw.get("policy_file", "mcode-policy.json")),
            skill_custom_dirs=tuple(str(item) for item in paths_raw.get("skill_custom_dirs", [])),
        ),
        runtime=RuntimeConfig(
            shell=str(runtime_raw.get("shell", "/bin/zsh")),
            python=str(runtime_raw.get("python", "")),
            python_preference=str(runtime_raw.get("python_preference", "conda")),
        ),
        ui=UiConfig(
            language=str(ui_raw.get("language", "zh")),
            theme=str(ui_raw.get("theme", "system")),
            file_open_app=str(ui_raw.get("file_open_app", "cursor")),
            show_thought_summary=_coerce_bool(ui_raw.get("show_thought_summary", True)),
        ),
    )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _config_path(path: Optional[str]) -> Path:
    if path:
        requested = Path(path)
        if requested.exists() or requested.name != "mcode-config.json":
            return requested
        legacy = requested.with_name("mini-agent-config.json")
        if legacy.exists():
            return legacy
        return requested
    default = Path("mcode-config.json")
    legacy = Path("mini-agent-config.json")
    return legacy if not default.exists() and legacy.exists() else default


def _env(primary: str, legacy: str, default: str) -> str:
    return os.environ.get(primary, os.environ.get(legacy, default))
