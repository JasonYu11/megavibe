from __future__ import annotations

from decimal import Decimal
import json

from app.bot.message_format import (
    format_balance_summary,
    format_copy_trade_notification,
    format_help_message,
    format_market_order_confirmation,
    format_order_detail,
    format_orders_summary,
    format_quote_summary,
    format_start_message,
    format_status_summary,
    format_token_amount,
    format_tracking_reference,
    short_address,
)
from app.copy_trading.models import CopyActionStatus, CopyTargetConfig, CopyTradeAction, CopyTradeActionGroup, CopyTradeIntent, CopyTradeKind, TokenTransfer
from app.core.order_info import MarketOrder
from app.core.order_info import TokenInfo
from app.orders.order_service import OrderServiceResult
from tests.test_order_info import market_payload


def test_short_address_truncates_evm_address() -> None:
    assert short_address("0x1234567890abcdef1234567890abcdef12345678") == "0x123456...5678"


def test_format_quote_summary_reads_okx_router_result() -> None:
    text = format_quote_summary(
        "USDC",
        "VIRTUAL",
        Decimal("2.000"),
        {
            "code": "0",
            "data": [
                {
                    "routerResult": {
                        "toTokenAmount": "10",
                        "minReceiveAmount": "9.9",
                        "priceImpactPercent": "0.2",
                    }
                }
            ],
        },
    )

    assert "报价\n" in text
    assert "路径: USDC -> VIRTUAL" in text
    assert "支付: 2 USDC" in text
    assert "预计获得: 10 VIRTUAL" in text
    assert "最小接收: 9.9" in text
    assert "价格影响: 0.2%" in text


def test_format_token_amount_converts_base_units_with_decimals() -> None:
    assert format_token_amount("1230000000000000000", 18) == "1.23"
    assert format_token_amount("990000", 6) == "0.99"
    assert format_token_amount("9.9", 18) == "9.9"


def test_quote_and_market_confirmation_convert_okx_base_units() -> None:
    quote = {
        "data": [
            {
                "routerResult": {
                    "toTokenAmount": "1230000000000000000",
                    "minReceiveAmount": "1200000000000000000",
                    "priceImpactPercent": "0.2",
                }
            }
        ]
    }
    quote_text = format_quote_summary("USDC", "VIRTUAL", Decimal("2"), quote, token_out_decimals=18)
    order = MarketOrder.from_dict(market_payload())
    result = OrderServiceResult(order.id, "PENDING_CONFIRMATION", quote, "APPROVED", None)
    confirmation_text = format_market_order_confirmation(order, result)

    assert "预计获得: 1.23 VIRTUAL" in quote_text
    assert "最小接收: 1.2 VIRTUAL" in quote_text
    assert "预计获得: 1.23 VIRTUAL" in confirmation_text
    assert "最小接收: 1.2 VIRTUAL" in confirmation_text


def test_format_tracking_reference_links_base_tx_hash() -> None:
    tx_hash = "0x" + "a" * 64

    text = format_tracking_reference(tx_hash)

    assert text == f"{tx_hash} https://www.oklink.com/base/tx/{tx_hash}"


def test_format_tracking_reference_handles_okx_order_id() -> None:
    assert format_tracking_reference("okx_order_1") == "OKX order id okx_order_1"


def test_format_balance_summary_accepts_debank_chain_balance_usd_value() -> None:
    assert format_balance_summary({"usd_value": "12.3400"}) == "钱包余额\n━━━━━━━━━━━━\n总估值: 12.34 USD"


def test_format_orders_summary_includes_amount_tokens_and_limit_price() -> None:
    market_payload = {
        "token_in": {"symbol": "USDC"},
        "token_out": {"symbol": "VIRTUAL"},
        "amount": {"value": "2"},
        "trade": {"side": "buy"},
    }
    conditional_payload = {
        "trigger": {
            "operator": ">=",
            "target_price_usd": "1.8",
            "token": {"symbol": "VIRTUAL"},
        },
        "action": {
            "token_in": {"symbol": "VIRTUAL"},
            "token_out": {"symbol": "USDC"},
            "amount": {"value": "10000"},
            "trade": {"side": "sell"},
        },
    }

    text = format_orders_summary(
        [{"id": "ord_1", "status": "PENDING_CONFIRMATION", "payload_json": json.dumps(market_payload)}],
        [{"id": "cond_1", "status": "ACTIVE", "payload_json": json.dumps(conditional_payload)}],
    )

    assert "当前订单" in text
    assert "市价单: ord_1" in text
    assert "状态: PENDING_CONFIRMATION" in text
    assert "🟢 买入: 使用 2 USDC 买入 VIRTUAL" in text
    assert "限价单: cond_1" in text
    assert "🔴 卖出: 到价后卖出 10000 VIRTUAL 换取 USDC" in text
    assert "条件: VIRTUAL >= 1.8 USD" in text


def test_start_and_help_messages_recommend_core_commands() -> None:
    start = format_start_message()
    help_text = format_help_message()

    assert "Base 交易助手" in start
    assert "/trade 流程引导" in start
    assert "/orders 当前订单" in start
    assert "命令说明" in help_text
    assert "/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE" in help_text


def test_format_order_detail_handles_market_and_conditional_rows() -> None:
    market_payload = {
        "token_in": {"symbol": "USDC"},
        "token_out": {"symbol": "VIRTUAL"},
        "amount": {"value": "2"},
        "trade": {"side": "buy"},
    }
    conditional_payload = {
        "trigger": {
            "operator": ">=",
            "target_price_usd": "1.8",
            "token": {"symbol": "VIRTUAL"},
        },
        "action": {"amount": {"value": "10000"}, "trade": {"side": "sell"}},
    }

    market_text = format_order_detail(
        {
            "order": {"id": "ord_1", "status": "BROADCASTED", "payload_json": json.dumps(market_payload)},
            "events": [{"id": 1}],
            "executions": [{"status": "BROADCASTED", "created_at": "2026-05-29T00:00:00Z", "tx_hash": "0x" + "a" * 64}],
        }
    )
    conditional_text = format_order_detail(
        {
            "conditional_order": {"id": "cond_1", "status": "ACTIVE", "payload_json": json.dumps(conditional_payload)},
            "events": [{"id": 1}],
        }
    )

    assert "市价单详情" in market_text
    assert "路径: 2 USDC->VIRTUAL" in market_text
    assert "Tx: 0x" in market_text
    assert "限价单详情" in conditional_text
    assert "条件: VIRTUAL >= 1.8 USD" in conditional_text


def test_format_status_summary_includes_runtime_health() -> None:
    text = format_status_summary(
        "dry_run",
        False,
        1,
        2,
        "orders.sqlite",
        "0x1234567890abcdef1234567890abcdef12345678",
        "123",
        "9",
        "true",
        "false",
    )

    assert "live_enabled=false" in text
    assert "钱包: 0x123456...5678" in text
    assert "watcher_ok=true" in text
    assert "receipt_ok=false" in text


def test_copy_trade_notification_uses_three_significant_digits_and_chinese_status() -> None:
    usdc = TokenInfo("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6)
    token = TokenInfo("ClawBank", "0x0000000000000000000000000000000000000001", 18)
    intent = CopyTradeIntent(
        kind=CopyTradeKind.STABLE_OR_ETH_TO_TOKEN,
        history_id="h1",
        tx_hash="0x" + "a" * 64,
        time_at=1000,
        sent=TokenTransfer(usdc, Decimal("0.012345")),
        received=TokenTransfer(token, Decimal("12345.6789")),
        estimated_usd_value=Decimal("0.012345"),
    )
    group = CopyTradeActionGroup(
        target=CopyTargetConfig(address="0x138ab382c889add23de09a78fd7a75b9b4fe5c25", copy_ratio=Decimal("0.1")),
        intent=intent,
        actions=[
            CopyTradeAction(
                label="买入",
                side="buy",
                token_in=usdc,
                token_out=token,
                amount=Decimal("0.0012345"),
                status=CopyActionStatus.SUBMITTED,
                order_id="ord_1",
                order_status="DRY_RUN_COMPLETED",
            ),
            CopyTradeAction(
                label="卖出",
                side="sell",
                token_in=token,
                token_out=usdc,
                amount=Decimal("0"),
                status=CopyActionStatus.FAILED,
                reason="balance_zero",
            ),
        ],
    )

    text = format_copy_trade_notification(group)

    assert "0.0123 USDC -> 12300 ClawBank" in text
    assert "估算金额: 0.0123 USD" in text
    assert "🟢 买入: 使用 0.00123 USDC 买入 ClawBank" in text
    assert "状态: 完成" in text
    assert "状态: 未完成" in text
    assert "FAILED" not in text
    assert "DRY_RUN_COMPLETED" not in text
