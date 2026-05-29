from __future__ import annotations

import pytest

from app.bot.command_catalog import (
    BLOCKED_NL_COMMANDS,
    NL_COMMAND_CATALOG,
    CommandCatalogError,
    nl_model_context,
    public_catalog_payload,
    resolve_token_address,
)


def test_nl_catalog_keeps_manual_only_commands_blocked() -> None:
    assert {"confirm", "reject", "cancel", "copy_confirm", "copy_remove"} <= BLOCKED_NL_COMMANDS
    assert not (set(NL_COMMAND_CATALOG) & BLOCKED_NL_COMMANDS)


def test_nl_catalog_public_payload_is_json_ready() -> None:
    payload = public_catalog_payload()

    assert {item["name"] for item in payload} >= {
        "status",
        "balance",
        "orders",
        "quote",
        "buy",
        "sell",
        "limit_buy",
        "limit_sell",
    }
    assert all("risk" in item and "required" in item for item in payload)


def test_nl_model_context_explains_base_evm_address_rules() -> None:
    context = nl_model_context()

    assert context["chain"] == "Base"
    assert "42 个字符" in context["token_address_rules"]
    assert "0x" in context["token_address_rules"]
    assert "40 位十六进制" in context["token_address_rules"]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("0x123", "42 个字符"),
        ("0xzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "十六进制"),
        ("5f980dcfc4c0fa3911554cf5ab288ed0eb13dba3", "缺少 0x 前缀"),
    ],
)
def test_resolve_token_address_reports_invalid_address_reason(value: str, reason: str) -> None:
    with pytest.raises(CommandCatalogError) as exc_info:
        resolve_token_address(value)

    assert "invalid token address" in str(exc_info.value)
    assert reason in str(exc_info.value)
