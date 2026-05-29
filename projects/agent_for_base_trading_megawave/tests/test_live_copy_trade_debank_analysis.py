from __future__ import annotations

import os

import pytest

from app.copy_trading.classifier import CopyTradeClassifier
from app.copy_trading.history_parser import DebankHistoryParser
from app.data.debank_client import DebankClient
from app.secrets.provider import EnvSecretProvider


@pytest.mark.skipif(os.environ.get("RUN_LIVE_DEBANK_TESTS") != "1", reason="live DeBank read-only test is gated")
def test_live_debank_copy_trade_history_analysis_when_enabled() -> None:
    address = os.environ.get("COPY_TRADE_TEST_ADDRESS", "0x138ab382c889add23de09a78fd7a75b9b4fe5c25")
    client = DebankClient("ENV:DEBANK_ACCESS_KEY", EnvSecretProvider())

    history = client.get_user_history(address, chain_id="base", page_count=5)
    parsed = DebankHistoryParser(max_age_seconds=300).parse(history)
    intents = [CopyTradeClassifier().classify(item) for item in parsed]

    assert isinstance(history.get("history_list"), list)
    assert all(intent.tx_hash for intent in intents)
