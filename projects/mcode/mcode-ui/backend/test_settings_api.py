from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as ui_app
from mini_agent_lab.provider import ProviderResponse


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_settings_defaults_and_update_preserve_unknowns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "mcode-config.json").write_text('{"custom": {"keep": true}}\n', encoding="utf-8")
        (root / "mcode-policy.json").write_text('{"auto_review": {"enabled": true, "model": "deepseek-chat"}}\n', encoding="utf-8")
        project, _ = ui_app.projects.create(name="settings-test", root_path=str(root))
        client = TestClient(ui_app.app)

        response = client.get(f"/api/projects/{project.id}/settings")
        _assert(response.status_code == 200, "GET settings succeeds")
        data = response.json()
        _assert(data["provider"]["model"] == "deepseek-v4-flash", "GET settings returns defaults")
        _assert(data["provider"]["thinking_mode"] is False, "GET settings returns thinking mode default")
        _assert(data["ui"]["show_thought_summary"] is True, "GET settings returns thought summary default")
        _assert(data["auto_review"]["enabled"] is True, "GET settings returns auto review policy")
        _assert("DEEPSEEK_API_KEY" not in response.text, "GET settings does not leak API key name/value")

        response = client.put(
            f"/api/projects/{project.id}/settings",
            json={
                "provider": {"timeout_seconds": 45, "model": "deepseek-v4-pro", "thinking_mode": True},
                "agent": {"max_steps": 33},
                "ui": {"show_thought_summary": False},
                "auto_review": {"enabled": False, "model": "deepseek-chat"},
            },
        )
        _assert(response.status_code == 200, "PUT settings succeeds")
        saved = response.json()
        _assert(saved["provider"]["timeout_seconds"] == 45, "PUT settings updates provider timeout")
        _assert(saved["provider"]["model"] == "deepseek-v4-pro", "PUT settings updates provider model")
        _assert(saved["provider"]["thinking_mode"] is True, "PUT settings updates thinking mode")
        _assert(saved["agent"]["max_steps"] == 33, "PUT settings updates agent max steps")
        _assert(saved["ui"]["show_thought_summary"] is False, "PUT settings updates thought summary toggle")
        _assert(saved["auto_review"]["enabled"] is False, "PUT settings updates auto review policy")
        raw = (root / "mcode-config.json").read_text(encoding="utf-8")
        _assert('"custom"' in raw, "PUT settings preserves unknown sections")
        _assert('"show_thought_summary": false' in raw, "PUT settings persists thought summary toggle")
        policy_raw = (root / "mcode-policy.json").read_text(encoding="utf-8")
        _assert('"enabled": false' in policy_raw, "PUT settings persists auto review policy")


def test_api_test_returns_mocked_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project, _ = ui_app.projects.create(name="api-test", root_path=str(root))
        client = TestClient(ui_app.app)

        with (
            patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}),
            patch("settings_api.DeepSeekProvider.complete", return_value=ProviderResponse(content="ok", raw_model="mock")),
        ):
            response = client.post(f"/api/projects/{project.id}/settings/api-test", json={"count": 2})

        _assert(response.status_code == 200, "API test endpoint succeeds with mocked provider")
        payload = response.json()
        _assert(payload["summary"]["total"] == 2, "API test reports requested sample size")
        _assert(payload["summary"]["ok"] == 2, "API test reports successful calls")


def test_api_key_is_stored_in_app_env_without_leaking() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        app_env = Path(tmp) / "appdata" / ".env"
        project, _ = ui_app.projects.create(name="api-key-test", root_path=str(root))
        client = TestClient(ui_app.app)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("settings_api.APP_ENV_PATH", app_env),
            patch("settings_api.REPO_ROOT", Path(tmp) / "runtime"),
            patch("settings_api.keychain.write_api_key", side_effect=RuntimeError("keychain unavailable")),
            patch("settings_api.keychain.read_api_key", return_value=""),
            patch("settings_api.keychain.delete_api_key", return_value=None),
        ):
            response = client.post(f"/api/projects/{project.id}/settings/api-key", json={"value": "sk-test-secret"})
            _assert(response.status_code == 200, "API key save endpoint succeeds")
            _assert(response.json()["api_key_configured"] is True, "saved API key is reported configured")
            _assert("sk-test-secret" not in response.text, "API key save response does not leak key")
            _assert(app_env.read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-test-secret\n", "API key is stored in app env")
            _assert((app_env.stat().st_mode & 0o777) == 0o600, "app env file is user-readable only")

            response = client.delete(f"/api/projects/{project.id}/settings/api-key")
            _assert(response.status_code == 200, "API key clear endpoint succeeds")
            _assert(response.json()["api_key_configured"] is False, "cleared API key is reported missing")
            _assert("DEEPSEEK_API_KEY" not in app_env.read_text(encoding="utf-8"), "API key is removed from app env")


def test_api_key_prefers_keychain_without_env_secret() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        app_env = Path(tmp) / "appdata" / ".env"
        project, _ = ui_app.projects.create(name="keychain-test", root_path=str(root))
        client = TestClient(ui_app.app)
        written: list[str] = []
        deleted: list[bool] = []

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("settings_api.APP_ENV_PATH", app_env),
            patch("settings_api.REPO_ROOT", Path(tmp) / "runtime"),
            patch("settings_api.keychain.write_api_key", side_effect=lambda value: written.append(value)),
            patch("settings_api.keychain.read_api_key", return_value="sk-keychain-secret"),
            patch("settings_api.keychain.delete_api_key", side_effect=lambda: deleted.append(True)),
        ):
            response = client.post(f"/api/projects/{project.id}/settings/api-key", json={"value": "sk-keychain-secret"})
            _assert(response.status_code == 200, "API key save endpoint succeeds with Keychain")
            _assert(written == ["sk-keychain-secret"], "API key is written to Keychain")
            _assert("sk-keychain-secret" not in response.text, "Keychain save response does not leak key")
            _assert(not app_env.exists() or "DEEPSEEK_API_KEY" not in app_env.read_text(encoding="utf-8"), "Keychain save avoids app env secret")
            response = client.get(f"/api/projects/{project.id}/settings")
            _assert(response.json()["api_key_configured"] is True, "Keychain API key is detected")
            response = client.delete(f"/api/projects/{project.id}/settings/api-key")
            _assert(response.status_code == 200, "API key clear endpoint succeeds with Keychain")
            _assert(deleted, "API key is deleted from Keychain")


if __name__ == "__main__":
    test_settings_defaults_and_update_preserve_unknowns()
    test_api_test_returns_mocked_summary()
    test_api_key_is_stored_in_app_env_without_leaking()
    test_api_key_prefers_keychain_without_env_secret()
    print("All settings API tests passed.")
