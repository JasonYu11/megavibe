from __future__ import annotations

from app.copy_trading.history_parser import DebankHistoryParser


USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TOKEN = "0x0000000000000000000000000000000000000001"


def history_item(**overrides):  # type: ignore[no-untyped-def]
    item = {
        "id": "hist_1",
        "chain": "base",
        "cate_id": "swap",
        "time_at": 1_000,
        "tx": {"status": 1, "id": "0xhash1"},
        "sends": [{"token_id": "usdc", "amount": "100"}],
        "receives": [{"token_id": "token", "amount": "5"}],
        "token_dict": {
            "usdc": {"id": USDC, "symbol": "USDC", "decimals": 6, "price": 1},
            "token": {"id": TOKEN, "symbol": "COIN", "decimals": 18, "price": "2"},
        },
    }
    item.update(overrides)
    return item


def test_parser_accepts_recent_base_swap() -> None:
    parser = DebankHistoryParser(max_age_seconds=300)

    parsed = parser.parse({"history_list": [history_item()]}, now_ts=1_120)

    assert len(parsed) == 1
    assert parsed[0].history_id == "hist_1"
    assert parsed[0].tx_hash == "0xhash1"
    assert parsed[0].sends[0].token.symbol == "USDC"
    assert parsed[0].receives[0].token.symbol == "COIN"
    assert parsed[0].receives[0].price_usd == 2


def test_parser_filters_old_non_base_approval_failed_and_one_sided_items() -> None:
    parser = DebankHistoryParser(max_age_seconds=300)
    items = [
        history_item(id="old", time_at=600),
        history_item(id="eth", chain="eth"),
        history_item(id="approve", cate_id="approve"),
        history_item(id="failed", tx={"status": 0}),
        history_item(id="send_only", receives=[]),
    ]

    parsed = parser.parse({"history_list": items}, now_ts=1_000)

    assert parsed == []


def test_parser_supports_dict_transfer_shape_and_raw_amount() -> None:
    parser = DebankHistoryParser()
    item = history_item(
        sends={"token_id": "usdc", "raw_amount": "1000000"},
        receives={"token_id": "token", "raw_amount": str(2 * 10**18)},
    )

    parsed = parser.parse({"history_list": [item]}, now_ts=1_100)

    assert parsed[0].sends[0].amount == 1
    assert parsed[0].receives[0].amount == 2
