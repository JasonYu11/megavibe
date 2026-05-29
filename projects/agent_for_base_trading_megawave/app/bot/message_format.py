from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core.order_info import ConditionalOrder, MarketOrder
from app.orders.order_service import OrderServiceResult

SEPARATOR = "━━━━━━━━━━━━"
SUB_SEPARATOR = "────────────"


def short_address(value: str, left: int = 6, right: int = 4) -> str:
    if not value.startswith("0x") or len(value) <= left + right + 2:
        return value
    return f"{value[:left + 2]}...{value[-right:]}"


def first_quote_item(quote: dict[str, Any]) -> dict[str, Any]:
    data = quote.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return quote


def nested_get(mapping: dict[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def format_decimal(value: Decimal | str | int | float) -> str:
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def format_significant(value: Decimal | str | int | float, digits: int = 3) -> str:
    try:
        decimal = Decimal(str(value))
    except Exception:
        return str(value)
    if not decimal.is_finite():
        return str(value)
    if decimal == 0:
        return "0"
    exponent = decimal.adjusted() - digits + 1
    quantized = decimal.quantize(Decimal(f"1e{exponent}"), rounding=ROUND_HALF_UP)
    return format_decimal(quantized)


def format_token_amount(value: Any, decimals: int | None = None) -> str:
    if decimals is None:
        return format_decimal(value)
    try:
        raw = Decimal(str(value))
    except Exception:
        return str(value)
    if not raw.is_finite():
        return str(value)
    if raw != raw.to_integral_value():
        return format_decimal(raw)
    return format_decimal(raw / (Decimal(10) ** decimals))


def format_signed_percent(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    text = format_decimal(rounded)
    if rounded > 0:
        return f"+{text}%"
    return f"{text}%"


def format_trade_theme(side: str) -> str:
    normalized = side.lower()
    if normalized == "buy":
        return "🟢 买入"
    if normalized == "sell":
        return "🔴 卖出"
    return side.upper()


def format_trade_action(
    side: str,
    amount: Decimal | str | int | float,
    token_in_symbol: str,
    token_out_symbol: str,
    prefix: str = "",
) -> str:
    amount_text = format_decimal(amount)
    theme = format_trade_theme(side)
    if side.lower() == "buy":
        return f"{theme}: {prefix}使用 {amount_text} {token_in_symbol} 买入 {token_out_symbol}"
    if side.lower() == "sell":
        return f"{theme}: {prefix}卖出 {amount_text} {token_in_symbol} 换取 {token_out_symbol}"
    return f"{theme}: {prefix}{amount_text} {token_in_symbol}->{token_out_symbol}"


def format_conditional_order_summary(
    order: ConditionalOrder,
    current_price_usd: Decimal | None = None,
) -> str:
    trigger = order.trigger
    action = order.action
    trade = action.get("trade") if isinstance(action.get("trade"), dict) else {}
    side = str(trade.get("side", "unknown"))
    token = trigger.token
    token_in = action.get("token_in", {}) if isinstance(action.get("token_in"), dict) else {}
    token_out = action.get("token_out", {}) if isinstance(action.get("token_out"), dict) else {}
    token_in_symbol = str(token_in.get("symbol", "?"))
    token_out_symbol = str(token_out.get("symbol", "?"))

    parts = [
        "限价单确认",
        SEPARATOR,
        "类型: 价格触发 / 自动执行",
        f"订单编号: {order.id}",
        format_trade_action(side, action["amount"]["value"], token_in_symbol, token_out_symbol, prefix="到价后"),
        SUB_SEPARATOR,
        f"触发条件: {token.symbol} {trigger.operator} {format_decimal(trigger.target_price_usd)} USD",
    ]
    if current_price_usd is None:
        parts.append("当前价格: 暂不可用")
    else:
        distance = ((trigger.target_price_usd - current_price_usd) / current_price_usd) * Decimal("100")
        parts.append(f"当前价格: {format_decimal(current_price_usd)} USD")
        parts.append(f"距离目标: {format_signed_percent(distance)}")
    parts.extend([SUB_SEPARATOR, "下一步: 确认后进入 watcher；到价后自动执行并通知"])
    return "\n".join(parts)


def format_market_order_confirmation(order: MarketOrder, result: OrderServiceResult) -> str:
    quote = result.quote or {}
    item = first_quote_item(quote)
    router = item.get("routerResult") if isinstance(item.get("routerResult"), dict) else {}
    to_amount = item.get("toTokenAmount") or router.get("toTokenAmount")
    min_receive = item.get("minReceiveAmount") or router.get("minReceiveAmount")
    price_impact = item.get("priceImpactPercent") or router.get("priceImpactPercent") or item.get("priceImpactPercent")

    lines = [
        "市价单确认",
        SEPARATOR,
        "类型: 即时市价 swap",
        f"订单编号: {order.id}",
        f"模式: {format_trade_theme(order.trade.side)} / {order.trade.route_provider.upper()}",
        SUB_SEPARATOR,
        format_trade_action(order.trade.side, order.amount.value, order.token_in.symbol, order.token_out.symbol),
        f"支付: {format_decimal(order.amount.value)} {order.token_in.symbol}",
        f"获得: {order.token_out.symbol}",
    ]
    if to_amount is not None:
        lines.append(f"预计获得: {format_token_amount(to_amount, order.token_out.decimals)} {order.token_out.symbol}")
    if min_receive is not None:
        lines.append(f"最小接收: {format_token_amount(min_receive, order.token_out.decimals)} {order.token_out.symbol}")
    if price_impact is not None:
        lines.append(f"价格影响: {price_impact}%")
    lines.extend(
        [
            f"最大滑点: {format_decimal(order.safety.max_slippage_percent)}%",
            f"风控结果: {result.risk_decision}",
            SUB_SEPARATOR,
            "下一步: 确认后提交执行",
        ]
    )
    return "\n".join(lines)


def format_quote_summary(
    token_in_symbol: str,
    token_out_symbol: str,
    amount: Decimal,
    quote: dict[str, Any],
    token_out_decimals: int | None = None,
) -> str:
    item = first_quote_item(quote)
    router = item.get("routerResult") if isinstance(item.get("routerResult"), dict) else {}
    price_impact = item.get("priceImpactPercent") or router.get("priceImpactPercent")
    min_receive = item.get("minReceiveAmount") or router.get("minReceiveAmount")
    to_amount = item.get("toTokenAmount") or router.get("toTokenAmount")

    parts = ["报价", SEPARATOR, f"路径: {token_in_symbol} -> {token_out_symbol}", SUB_SEPARATOR, f"支付: {format_decimal(amount)} {token_in_symbol}"]
    if to_amount is not None:
        parts.append(f"预计获得: {format_token_amount(to_amount, token_out_decimals)} {token_out_symbol}")
    if min_receive is not None:
        parts.append(f"最小接收: {format_token_amount(min_receive, token_out_decimals)} {token_out_symbol}")
    if price_impact is not None:
        parts.append(f"价格影响: {price_impact}%")
    return "\n".join(parts)


def format_balance_summary(balance: dict[str, Any]) -> str:
    total = balance.get("total_usd_value")
    if total is None:
        total = balance.get("usd_value")
    if total is None:
        return "余额已获取"
    lines = ["钱包余额", SEPARATOR, f"总估值: {format_decimal(total)} USD"]
    key_tokens = balance.get("key_tokens")
    if isinstance(key_tokens, list):
        for token in key_tokens:
            if not isinstance(token, dict):
                continue
            symbol = token.get("symbol")
            amount = token.get("amount")
            usd_value = token.get("usd_value")
            if symbol and amount is not None:
                suffix = f" ≈ {format_decimal(usd_value)} USD" if usd_value is not None else ""
                lines.append(f"{symbol}: {format_decimal(amount)}{suffix}")
    return "\n".join(lines)


def format_orders_summary(
    orders: list[dict[str, Any]],
    conditional_orders: list[dict[str, Any]],
    title: str = "当前订单",
) -> str:
    parts = [title, SEPARATOR, f"市价单: {len(orders)}", f"限价单: {len(conditional_orders)}"]
    if not orders and not conditional_orders:
        parts.append("暂无订单")
        return "\n".join(parts)
    for row in orders[:5]:
        payload = _payload(row)
        token_in = payload.get("token_in", {}).get("symbol", "?") if isinstance(payload.get("token_in"), dict) else "?"
        token_out = payload.get("token_out", {}).get("symbol", "?") if isinstance(payload.get("token_out"), dict) else "?"
        amount = payload.get("amount", {}).get("value", "?") if isinstance(payload.get("amount"), dict) else "?"
        side = payload.get("trade", {}).get("side", "swap") if isinstance(payload.get("trade"), dict) else "swap"
        tx = row.get("last_tx_hash")
        tx_part = f" tx={format_tracking_reference(str(tx))}" if tx else ""
        parts.append(SUB_SEPARATOR)
        parts.append(f"市价单: {row.get('id')}")
        parts.append(f"  状态: {row.get('status')}")
        parts.append(f"  {format_trade_action(str(side), amount, str(token_in), str(token_out))}{tx_part}")
    for row in conditional_orders[:5]:
        payload = _payload(row)
        trigger = payload.get("trigger", {}) if isinstance(payload.get("trigger"), dict) else {}
        action = payload.get("action", {}) if isinstance(payload.get("action"), dict) else {}
        trade = action.get("trade", {}) if isinstance(action.get("trade"), dict) else {}
        amount = action.get("amount", {}).get("value", "?") if isinstance(action.get("amount"), dict) else "?"
        token = trigger.get("token", {}).get("symbol", "?") if isinstance(trigger.get("token"), dict) else "?"
        token_in = action.get("token_in", {}).get("symbol", "?") if isinstance(action.get("token_in"), dict) else "?"
        token_out = action.get("token_out", {}).get("symbol", "?") if isinstance(action.get("token_out"), dict) else "?"
        parts.append(SUB_SEPARATOR)
        parts.append(f"限价单: {row.get('id')}")
        parts.append(f"  状态: {row.get('status')}")
        parts.append(f"  {format_trade_action(str(trade.get('side', '?')), amount, str(token_in), str(token_out), prefix='到价后')}")
        parts.append(
            f"  条件: {token} {trigger.get('operator', '?')} {trigger.get('target_price_usd', '?')} USD"
        )
    return "\n".join(parts)


def format_start_message() -> str:
    return "\n".join(
        [
            "Base 交易助手",
            SEPARATOR,
            "模式: Base / USDC 默认中间资产",
            SUB_SEPARATOR,
            "交易",
            "/trade 流程引导",
            "/buy 市价买入",
            "/sell 市价卖出",
            "/limit_buy 限价买入",
            "/limit_sell 限价卖出",
            "",
            "管理",
            "/orders 当前订单",
            "/history 历史订单",
            "/balance 钱包余额",
            "/status 运行状态",
            "/copy_add 添加跟单地址",
            "/copy_list 跟单管理",
            SUB_SEPARATOR,
            "原生 ETH 地址: 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        ]
    )


def format_help_message() -> str:
    return "\n".join(
        [
            "命令说明",
            SEPARATOR,
            "市价单",
            "/buy TOKEN_OUT_ADDRESS AMOUNT",
            "  用 AMOUNT USDC 市价买入 token",
            "/sell TOKEN_IN_ADDRESS AMOUNT",
            "  卖出 AMOUNT token，默认换成 USDC",
            "",
            "限价单",
            "/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE",
            "  当 token USD 价格 <= 目标价时，用 AMOUNT USDC 自动买入",
            "/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE",
            "  当 token USD 价格 >= 目标价时，自动卖出 AMOUNT token",
            "",
            "查询与管理",
            "/quote TOKEN_IN TOKEN_OUT AMOUNT",
            "  查询 OKX 路由报价",
            "/orders",
            "  查看当前待处理和监控中的订单",
            "/history",
            "  查看最近历史订单",
            "/order ORDER_ID",
            "  查看单个订单详情",
            "/cancel ORDER_ID",
            "  取消待确认或监控中的订单",
            "",
            "跟单",
            "/copy_add ADDRESS",
            "  添加 Base 跟单地址，先审核再启用",
            "/copy_set ADDRESS ratio 0.00001 max 0.01",
            "  设置跟单比例和单笔上限",
            "/copy_list",
            "  查看跟单地址",
            "/copy_pause ADDRESS / /copy_resume ADDRESS / /copy_remove ADDRESS",
            "  管理跟单地址",
        ]
    )


def format_status_summary(
    execution_mode: str,
    live_enabled: bool,
    market_count: int,
    conditional_count: int,
    db_path: str,
    wallet_address: str | None,
    heartbeat_at: str | None,
    telegram_offset: str | None,
    watcher_last_ok: str | None = None,
    receipt_last_ok: str | None = None,
    copy_watcher_ok: str | None = None,
) -> str:
    heartbeat = heartbeat_at or "none"
    offset = telegram_offset or "none"
    watcher = watcher_last_ok or "unknown"
    receipt = receipt_last_ok or "unknown"
    copy = copy_watcher_ok or "unknown"
    return (
        f"运行状态\n{SEPARATOR}\n"
        f"模式: {execution_mode.upper()}\n"
        f"live: {'已开启' if live_enabled else '已关闭'}\n"
        f"execution_mode={execution_mode}\n"
        f"live_enabled={str(live_enabled).lower()}\n"
        f"钱包: {short_address(wallet_address) if wallet_address else 'unknown'}\n"
        f"{SUB_SEPARATOR}\n"
        f"当前市价单: {market_count}\n"
        f"当前限价单: {conditional_count}\n"
        f"{SUB_SEPARATOR}\n"
        f"DB: {db_path}\n"
        f"heartbeat={heartbeat}\n"
        f"telegram_offset={offset}\n"
        f"watcher_ok={watcher}\n"
        f"copy_watcher_ok={copy}\n"
        f"receipt_ok={receipt}"
    )


def format_copy_target_review(target: Any) -> str:
    return "\n".join(
        [
            "跟单地址确认",
            SEPARATOR,
            f"地址: {short_address(target.address)}",
            "公链: Base",
            f"安全窗口: {int(target.max_age_seconds / 60)} 分钟",
            f"默认比例: {format_decimal(target.copy_ratio)}",
            f"最大单笔: {format_decimal(target.max_copy_trade_usd)} USDC",
            SUB_SEPARATOR,
            "规则",
            "- 只跟 Base 交易",
            "- 只跟 5 分钟内新交易",
            "- 忽略单边转账和 approve/transfer",
            "- 第一版仅 dry-run 自动执行",
        ]
    )


def format_copy_target_enabled(target: Any, title: str = "跟单已启用") -> str:
    return "\n".join(
        [
            title,
            SEPARATOR,
            f"地址: {short_address(target.address)}",
            f"比例: {format_decimal(target.copy_ratio)}",
            f"最大单笔: {format_decimal(target.max_copy_trade_usd)} USDC",
            f"安全窗口: {int(target.max_age_seconds / 60)} 分钟",
            f"状态: {target.status.value if hasattr(target.status, 'value') else target.status}",
        ]
    )


def format_copy_targets_summary(targets: list[Any], events: list[dict[str, Any]] | None = None) -> str:
    parts = ["跟单管理", SEPARATOR, f"地址数: {len(targets)}"]
    if not targets:
        parts.append("暂无跟单地址")
        return "\n".join(parts)
    for target in targets:
        parts.append(SUB_SEPARATOR)
        parts.append(f"地址: {short_address(target.address)}")
        parts.append(f"状态: {target.status.value if hasattr(target.status, 'value') else target.status}")
        parts.append(f"比例: {format_decimal(target.copy_ratio)}")
        parts.append(f"最大单笔: {format_decimal(target.max_copy_trade_usd)} USDC")
    if events:
        parts.append(SUB_SEPARATOR)
        parts.append("最近跟单事件")
        for event in events[:3]:
            parts.append(f"{event.get('status')}: {short_address(str(event.get('tx_hash', '')))}")
    return "\n".join(parts)


def format_copy_trade_notification(group: Any) -> str:
    intent = group.intent
    target = group.target
    source = (
        f"{format_significant(intent.sent.amount)} {intent.sent.token.symbol} -> "
        f"{format_significant(intent.received.amount)} {intent.received.token.symbol}"
    )
    parts = [
        "跟单触发",
        SEPARATOR,
        f"源地址: {short_address(target.address)}",
        f"源交易: {source}",
        f"Tx: {short_address(intent.tx_hash)}",
        f"比例: {format_significant(target.copy_ratio)}",
        f"估算金额: {format_significant(intent.estimated_usd_value)} USD",
        SUB_SEPARATOR,
        "执行动作",
    ]
    for action in group.actions:
        if action.side in {"buy", "sell"} and action.token_in and action.token_out:
            parts.append(_format_copy_trade_action(action))
        else:
            parts.append(f"{action.label}: {action.side}")
        status = action.order_status or (action.status.value if hasattr(action.status, "value") else action.status)
        parts.append(f"状态: {_copy_status_label(str(status))}")
        if action.order_id:
            parts.append(f"订单: {action.order_id}")
        if action.reason:
            parts.append(f"原因: {_copy_reason(action.reason)}")
    return "\n".join(parts)


def _copy_reason(reason: str) -> str:
    if reason.startswith("quote_unavailable:"):
        return f"OKX 暂无可用报价: {reason.split(':', 1)[1].strip()}"
    return {
        "balance_zero": "本地余额为 0",
        "amount_zero": "跟单金额为 0",
        "amount_below_token_precision": "跟单金额低于 token 最小精度",
        "copy_auto_execution_requires_dry_run": "跟单 v1 只允许 dry-run 自动执行",
        "copy_auto_execution_requires_dry_run_or_live": "跟单自动执行只支持 dry-run 或已授权 live",
        "copy_live_disabled": "真实跟单未开启，需要 CONFIRM_LIVE_COPY_TRADE_BASE=YES",
        "copy_live_base_gate_disabled": "真实交易总开关未开启",
        "token_not_allowed": "token 未被当前风控允许",
        "max_single_trade_usd": "超过单笔交易上限",
        "max_daily_trade_usd": "超过当日交易上限",
        "insufficient_balance": "本地钱包余额不足",
    }.get(reason, reason)


def _format_copy_trade_action(action: Any) -> str:
    amount_text = format_significant(action.amount)
    theme = format_trade_theme(action.side)
    if action.side.lower() == "buy":
        return f"{theme}: 使用 {amount_text} {action.token_in.symbol} 买入 {action.token_out.symbol}"
    if action.side.lower() == "sell":
        return f"{theme}: 卖出 {amount_text} {action.token_in.symbol} 换取 {action.token_out.symbol}"
    return f"{theme}: {amount_text} {action.token_in.symbol}->{action.token_out.symbol}"


def _copy_status_label(status: str) -> str:
    normalized = status.upper()
    if normalized in {"DRY_RUN_COMPLETED", "SUBMITTED", "BROADCASTED", "FILLED", "SIGNED_NOT_BROADCASTED"}:
        return "完成"
    if normalized in {"PENDING", "PENDING_CONFIRMATION", "SIGNING"}:
        return "处理中"
    if normalized in {"SKIPPED"}:
        return "已跳过"
    if normalized in {"FAILED"}:
        return "未完成"
    return status


def format_limit_trigger_notification(
    conditional_order_id: str,
    current_price: Decimal | str,
    market_order_id: str,
    market_order_status: str,
    tracking_id: str | None = None,
) -> str:
    lines = [
        "限价单已自动执行",
        SEPARATOR,
        f"限价单: {conditional_order_id}",
        f"触发价格: {format_decimal(current_price)} USD",
        SUB_SEPARATOR,
        f"市价单: {market_order_id}",
        f"执行状态: {market_order_status}",
    ]
    if tracking_id:
        lines.append(f"交易追踪: {format_tracking_reference(tracking_id)}")
    lines.append("系统已按限价单规则自动处理，无需二次确认")
    return "\n".join(lines)


def format_execution_result(
    result: OrderServiceResult,
    execution: dict[str, Any] | None = None,
    quote: dict[str, Any] | None = None,
    balance: dict[str, Any] | None = None,
    token_out_symbol: str | None = None,
    token_out_decimals: int | None = None,
) -> str:
    lines = ["交易结果", SEPARATOR, f"状态: {result.status}", f"订单编号: {result.order_id}"]
    if result.tracking_id:
        lines.append(f"交易追踪: {format_tracking_reference(result.tracking_id)}")
    if execution is not None and execution.get("created_at"):
        lines.append(f"提交时间: {execution['created_at']}")
    if quote is not None:
        item = first_quote_item(quote)
        router = item.get("routerResult") if isinstance(item.get("routerResult"), dict) else {}
        to_amount = item.get("toTokenAmount") or router.get("toTokenAmount")
        min_receive = item.get("minReceiveAmount") or router.get("minReceiveAmount")
        price_impact = item.get("priceImpactPercent") or router.get("priceImpactPercent") or item.get("priceImpactPercent")
        if to_amount is not None:
            suffix = f" {token_out_symbol}" if token_out_symbol else ""
            lines.append(f"预计成交量: {format_token_amount(to_amount, token_out_decimals)}{suffix}")
        if min_receive is not None:
            suffix = f" {token_out_symbol}" if token_out_symbol else ""
            lines.append(f"最小接收: {format_token_amount(min_receive, token_out_decimals)}{suffix}")
        if price_impact is not None:
            lines.append(f"价格影响: {price_impact}%")
    if result.status == "BROADCASTED":
        lines.append("成交价格: 等待链上回执/DeBank 解析")
    if balance is not None:
        lines.append("")
        lines.append(format_balance_summary(balance))
    else:
        lines.append("余额: 为节省 API 调用未自动查询，需要时输入 /balance")
    return "\n".join(lines)


def format_order_detail(detail: dict[str, Any]) -> str:
    row = detail.get("order")
    kind = "市价单"
    if row is None:
        row = detail.get("conditional_order")
        kind = "限价单"
    if row is None:
        return "未找到订单"

    payload = _payload(row)
    lines = [f"{kind}详情", SEPARATOR, f"订单编号: {row.get('id')}", f"状态: {row.get('status')}", SUB_SEPARATOR]
    if kind == "市价单":
        token_in = payload.get("token_in", {}).get("symbol", "?") if isinstance(payload.get("token_in"), dict) else "?"
        token_out = payload.get("token_out", {}).get("symbol", "?") if isinstance(payload.get("token_out"), dict) else "?"
        amount = payload.get("amount", {}).get("value", "?") if isinstance(payload.get("amount"), dict) else "?"
        trade = payload.get("trade", {}) if isinstance(payload.get("trade"), dict) else {}
        lines.append(format_trade_action(str(trade.get("side", "swap")), amount, str(token_in), str(token_out)))
        lines.append(f"路径: {amount} {token_in}->{token_out}")
    else:
        trigger = payload.get("trigger", {}) if isinstance(payload.get("trigger"), dict) else {}
        action = payload.get("action", {}) if isinstance(payload.get("action"), dict) else {}
        trade = action.get("trade", {}) if isinstance(action.get("trade"), dict) else {}
        amount = action.get("amount", {}).get("value", "?") if isinstance(action.get("amount"), dict) else "?"
        token = trigger.get("token", {}).get("symbol", "?") if isinstance(trigger.get("token"), dict) else "?"
        token_in = action.get("token_in", {}).get("symbol", "?") if isinstance(action.get("token_in"), dict) else "?"
        token_out = action.get("token_out", {}).get("symbol", "?") if isinstance(action.get("token_out"), dict) else "?"
        lines.append(format_trade_action(str(trade.get("side", "?")), amount, str(token_in), str(token_out), prefix="到价后"))
        lines.append(f"条件: {token} {trigger.get('operator', '?')} {trigger.get('target_price_usd', '?')} USD")

    approvals = detail.get("approvals") or []
    executions = detail.get("executions") or []
    events = detail.get("events") or []
    if approvals:
        last = approvals[-1]
        lines.append(f"最近确认: {last.get('decision')} / {last.get('created_at')}")
    if executions:
        last = executions[-1]
        lines.append(f"最近执行: {last.get('status')} / {last.get('created_at')}")
        if last.get("tx_hash"):
            lines.append(f"Tx: {format_tracking_reference(str(last['tx_hash']))}")
    if events:
        lines.append(f"事件数: {len(events)}")
    return "\n".join(lines)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json")
    if not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def format_tracking_reference(tracking_id: str) -> str:
    if tracking_id.startswith("0x") and len(tracking_id) == 66:
        return f"{tracking_id} https://www.oklink.com/base/tx/{tracking_id}"
    return f"OKX order id {tracking_id}"
