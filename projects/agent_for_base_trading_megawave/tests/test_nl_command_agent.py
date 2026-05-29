from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.bot.nl_command_agent import DeepSeekClient, DeepSeekConfigError, NLCommandAgent


ROOT = Path(__file__).resolve().parents[1]


class FixtureClient:
    def __init__(self, payload: dict[str, Any], review: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.review = review or {"approved": True, "summary": "审查通过", "warnings": []}
        self.calls: list[str] = []
        self.messages: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        self.calls.append(purpose)
        self.messages.append(messages)
        if purpose == "review":
            return self.review
        return self.payload


def _cases() -> list[dict[str, Any]]:
    return json.loads((ROOT / "tests/fixtures/nl_command_cases.json").read_text(encoding="utf-8"))


def test_nl_agent_maps_simulated_cases_with_mock_llm() -> None:
    for case in _cases():
        client = FixtureClient(case["mock_intent"], case.get("mock_review"))
        result = NLCommandAgent(client=client).parse(case["text"]).to_dict()
        expected = case["expected"]

        assert result["status"] == expected["status"], case["id"]
        if "command" in expected:
            assert result["command"] == expected["command"].lower(), case["id"]
        if "risk" in expected:
            assert result["risk"] == expected["risk"], case["id"]
        if "missing_fields" in expected:
            assert result["missing_fields"] == expected["missing_fields"], case["id"]


def test_nl_agent_blocks_manual_confirmation_before_llm_call() -> None:
    client = FixtureClient({"status": "mapped", "intent": "confirm", "slots": {"order_id": "ord_1"}})

    result = NLCommandAgent(client=client).parse("帮我确认 ord_1")

    assert result.status == "blocked_manual_only"
    assert client.calls == []


def test_nl_agent_rejects_hallucinated_blocked_intent_from_llm() -> None:
    client = FixtureClient({"status": "mapped", "intent": "cancel", "slots": {"order_id": "ord_1"}})

    result = NLCommandAgent(client=client).parse("处理一下 ord_1")

    assert result.status == "blocked_manual_only"
    assert result.command is None


def test_nl_agent_uses_review_gate_for_trade_drafts() -> None:
    client = FixtureClient(
        {
            "status": "mapped",
            "intent": "buy",
            "slots": {"token_out": "VIRTUAL", "amount": "0.01"},
            "summary": "买入 VIRTUAL",
        }
    )

    result = NLCommandAgent(client=client).parse("按刚才讨论的交易想法处理 VIRTUAL")

    assert result.status == "mapped"
    assert client.calls == ["intent", "review"]
    assert result.command == "/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01"


def test_nl_agent_fast_path_maps_common_trade_without_llm() -> None:
    client = FixtureClient({"status": "unmapped"})

    result = NLCommandAgent(client=client).parse("用 0.01U 买 VIRTUAL")

    assert result.status == "mapped"
    assert client.calls == []
    assert result.command == "/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01"


def test_nl_agent_fast_path_ignores_numbers_inside_token_addresses() -> None:
    client = FixtureClient({"status": "unmapped"})

    result = NLCommandAgent(client=client).parse("买 1 个 0x5f980dcfc4c0fa3911554cf5ab288ed0eb13dba3")

    assert result.status == "mapped"
    assert client.calls == []
    assert result.command == "/buy 0x5f980dcfc4c0fa3911554cf5ab288ed0eb13dba3 1"


def test_nl_agent_does_not_treat_address_prefix_as_amount() -> None:
    client = FixtureClient(
        {
            "status": "clarification_required",
            "intent": "buy",
            "missing_fields": ["amount"],
            "summary": "缺少买入数量",
        }
    )

    result = NLCommandAgent(client=client).parse("买 0x5f980dcfc4c0fa3911554cf5ab288ed0eb13dba3")

    assert result.status == "clarification_required"
    assert result.command is None
    assert result.missing_fields == ["amount"]
    assert client.calls == ["intent"]


def test_nl_agent_rejects_zero_amount_before_parser_preview() -> None:
    client = FixtureClient(
        {
            "status": "mapped",
            "intent": "buy",
            "slots": {"token_out": "0x5f980dcfc4c0fa3911554cf5ab288ed0eb13dba3", "amount": "0"},
            "summary": "买入指定 token",
        }
    )

    result = NLCommandAgent(client=client).parse("买这个 token")

    assert result.status == "clarification_required"
    assert result.command is None
    assert result.missing_fields == ["amount"]


def test_nl_agent_returns_invalid_address_reason_from_model_slots() -> None:
    client = FixtureClient(
        {
            "status": "mapped",
            "intent": "buy",
            "slots": {"token_out": "0x123", "amount": "1"},
            "summary": "买入指定 token",
        }
    )

    result = NLCommandAgent(client=client).parse("买 1 个 0x123")

    assert result.status == "clarification_required"
    assert result.command is None
    assert "42 个字符" in result.summary


def test_nl_agent_prompt_contains_address_context() -> None:
    client = FixtureClient(
        {
            "status": "clarification_required",
            "intent": "buy",
            "missing_fields": ["token_out"],
            "summary": "地址格式不正确",
        }
    )

    NLCommandAgent(client=client).parse("帮我买 0x123")

    system_prompt = client.messages[0][0]["content"]
    assert "Base" in system_prompt
    assert "42 个字符" in system_prompt
    assert "0x" in system_prompt
    assert "40 位十六进制" in system_prompt


def test_nl_agent_surfaces_missing_deepseek_configuration(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_from_env() -> DeepSeekClient:
        raise DeepSeekConfigError("DEEPSEEK_API_KEY is not configured")

    monkeypatch.setattr(DeepSeekClient, "from_env", fail_from_env)

    result = NLCommandAgent(client=None).parse("帮我用 0.01 买这个币")

    assert result.status == "configuration_error"
    assert "DEEPSEEK" in result.summary
