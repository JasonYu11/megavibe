from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.bot.command_parser import CommandParseError, TelegramCommandParser
from app.bot.guided_flow import GuidedFlowError, GuidedTradeFlow
from app.bot.message_format import (
    format_balance_summary,
    format_conditional_order_summary,
    format_copy_target_enabled,
    format_copy_target_review,
    format_copy_targets_summary,
    format_execution_result,
    format_help_message,
    format_market_order_confirmation,
    format_order_detail,
    format_orders_summary,
    format_quote_summary,
    format_start_message,
    format_status_summary,
)
from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.core.order_info import ConditionalOrder, MarketOrder
from app.core.order_state import ConditionalOrderStatus, OrderStatus
from app.orders.order_service import OrderService, OrderServiceResult
from app.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class HandlerResponse:
    text: str
    payload: dict[str, Any]
    reply_markup: dict[str, Any] | None = None


@dataclass
class TelegramCommandHandler:
    parser: TelegramCommandParser
    order_service: OrderService
    store: SQLiteStore
    balance_service: Any | None = None
    price_provider: Any | None = None
    guided_flow: GuidedTradeFlow | None = None
    allowed_user_ids: set[str] | None = None
    allowed_chat_ids: set[str] | None = None

    def handle(self, text: str, actor: str = "telegram", chat_id: str | None = None) -> HandlerResponse:
        if not self._is_authorized(actor, chat_id):
            return HandlerResponse(text="Unauthorized", payload={"command": "auth", "status": "UNAUTHORIZED"})
        flow_chat_id = chat_id or actor
        if self.guided_flow is not None and text.strip().lower() == "/trade":
            result = self.guided_flow.start(flow_chat_id, actor)
            return HandlerResponse(
                text=result.text,
                payload={"command": "trade", "status": "STARTED"},
                reply_markup=self._trade_type_buttons(),
            )
        if self.guided_flow is not None and self.guided_flow.is_active(flow_chat_id, actor):
            try:
                result = self.guided_flow.handle(flow_chat_id, actor, text)
            except GuidedFlowError as exc:
                return HandlerResponse(text=f"Trade flow error: {exc}", payload={"command": "trade", "status": "ERROR", "reason": str(exc)})
            if result.cancelled:
                return HandlerResponse(text=result.text, payload={"command": "trade", "status": "CANCELLED"})
            if result.order is None:
                return HandlerResponse(
                    text=result.text,
                    payload={"command": "trade", "status": "IN_PROGRESS"},
                    reply_markup=self._guided_review_buttons() if "Send Confirm" in result.text else None,
                )
            return self._handle_order(result.order)

        try:
            parsed = self.parser.parse(text)
        except CommandParseError as exc:
            return HandlerResponse(text=f"Command error: {exc}", payload={"command": "error", "reason": str(exc)})
        return self._handle_parsed(parsed, actor=actor)

    def handle_callback(self, data: str, actor: str = "telegram", chat_id: str | None = None) -> HandlerResponse:
        if data.startswith("confirm:"):
            return self.handle(f"/confirm {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data.startswith("reject:"):
            return self.handle(f"/reject {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data.startswith("cancel:"):
            return self.handle(f"/cancel {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data.startswith("copy_confirm:"):
            return self.handle(f"/copy_confirm {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data.startswith("copy_cancel:"):
            return self.handle(f"/copy_remove {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data == "trade:start":
            return self.handle("/trade", actor=actor, chat_id=chat_id)
        if data == "nav:start":
            return self.handle("/start", actor=actor, chat_id=chat_id)
        if data == "nav:orders":
            return self.handle("/orders", actor=actor, chat_id=chat_id)
        if data == "nav:history":
            return self.handle("/history", actor=actor, chat_id=chat_id)
        if data == "nav:copy_status":
            return self.handle("/copy_status", actor=actor, chat_id=chat_id)
        if data.startswith("order:"):
            return self.handle(f"/order {data.split(':', 1)[1]}", actor=actor, chat_id=chat_id)
        if data.startswith("trade:"):
            return self.handle(data.split(":", 1)[1].replace("_", " "), actor=actor, chat_id=chat_id)
        return HandlerResponse(text="Unsupported callback", payload={"command": "callback", "status": "UNSUPPORTED"})

    def _handle_parsed(self, parsed: MarketOrder | ConditionalOrder | dict, actor: str) -> HandlerResponse:
        if isinstance(parsed, MarketOrder):
            return self._handle_order(parsed)
        if isinstance(parsed, ConditionalOrder):
            return self._handle_order(parsed)
        command = parsed.get("command")
        if command == "confirm":
            conditional_row = self.store.get_conditional_order(parsed["order_id"])
            if conditional_row is not None:
                return self._confirm_conditional_order(conditional_row, actor)
            if self.order_service.execution_mode == "live" and not self.order_service.live_enabled:
                return HandlerResponse(
                    text="实盘执行已关闭：需要 execution_mode=live 且 RUN_LIVE_TRADE_TESTS=1、CONFIRM_LIVE_TRADE_BASE=YES",
                    payload={"order_id": parsed["order_id"], "status": "LIVE_DISABLED"},
                )
            result = self.order_service.confirm_order(parsed["order_id"], actor=actor)
            return HandlerResponse(text=self._format_order_result(result, include_details=True), payload={"order_id": result.order_id, "status": result.status})
        if command == "reject":
            conditional_row = self.store.get_conditional_order(parsed["order_id"])
            if conditional_row is not None:
                return self._reject_conditional_order(conditional_row, actor)
            result = self.order_service.reject_order(parsed["order_id"], actor=actor)
            return HandlerResponse(text=self._format_order_result(result), payload={"order_id": result.order_id, "status": result.status})
        if command == "cancel":
            order_id = parsed["order_id"]
            row = self.store.get_order(order_id)
            if row is not None:
                self.store.update_order_status(order_id, OrderStatus.CANCELLED, {"cancelled_by": actor})
                return HandlerResponse(text=f"订单已取消: {order_id}", payload={"order_id": order_id, "status": OrderStatus.CANCELLED.value})
            try:
                self.store.update_conditional_status(order_id, ConditionalOrderStatus.CANCELLED, {"cancelled_by": actor})
            except KeyError:
                return HandlerResponse(text=f"未找到订单: {order_id}", payload={"order_id": order_id, "status": "NOT_FOUND"})
            return HandlerResponse(
                text=f"限价单已取消: {order_id}",
                payload={"order_id": order_id, "status": ConditionalOrderStatus.CANCELLED.value},
            )
        if command == "status":
            orders = self.store.list_current_orders(limit=5)
            conditional = self.store.list_current_conditional_orders(limit=5)
            copy_targets = self.store.list_copy_targets()
            wallet_address = self._wallet_address()
            return HandlerResponse(
                text=format_status_summary(
                    execution_mode=self.order_service.execution_mode,
                    live_enabled=self.order_service.live_enabled,
                    market_count=len(orders),
                    conditional_count=len(conditional),
                    db_path=str(self.store.db_path),
                    wallet_address=wallet_address,
                    heartbeat_at=self.store.get_runtime_value("heartbeat_at"),
                    telegram_offset=self.store.get_runtime_value("telegram_offset"),
                    watcher_last_ok=self.store.get_runtime_value("watcher_last_ok"),
                    receipt_last_ok=self.store.get_runtime_value("receipt_last_ok"),
                    copy_watcher_ok=self.store.get_runtime_value("copy_watcher_ok"),
                ),
                payload={
                    "command": "status",
                    "orders": len(orders),
                    "conditional_orders": len(conditional),
                    "execution_mode": self.order_service.execution_mode,
                    "live_enabled": self.order_service.live_enabled,
                    "wallet_address": wallet_address,
                    "heartbeat_at": self.store.get_runtime_value("heartbeat_at"),
                    "telegram_offset": self.store.get_runtime_value("telegram_offset"),
                    "watcher_last_ok": self.store.get_runtime_value("watcher_last_ok"),
                    "receipt_last_ok": self.store.get_runtime_value("receipt_last_ok"),
                    "copy_watcher_ok": self.store.get_runtime_value("copy_watcher_ok"),
                    "copy_targets": len(copy_targets),
                },
            )
        if command == "start":
            return HandlerResponse(
                text=format_start_message(),
                payload={"command": "start"},
                reply_markup=self._home_buttons(),
            )
        if command == "help":
            return HandlerResponse(text=format_help_message(), payload={"command": "help"})
        if command == "mode":
            live = "已开启" if self.order_service.live_enabled else "已关闭"
            return HandlerResponse(
                text=f"运行模式: execution_mode={self.order_service.execution_mode}\nlive={live}",
                payload={"command": "mode", "execution_mode": self.order_service.execution_mode, "live_enabled": self.order_service.live_enabled},
            )
        if command == "orders":
            orders = self.store.list_current_orders(limit=10)
            conditional = self.store.list_current_conditional_orders(limit=10)
            order_rows = [self._order_row_with_execution(row) for row in orders]
            conditional_rows = [dict(row) for row in conditional]
            return HandlerResponse(
                text=format_orders_summary(order_rows, conditional_rows, title="当前订单"),
                payload={
                    "command": "orders",
                    "orders": order_rows,
                    "conditional_orders": conditional_rows,
                },
                reply_markup=self._orders_buttons(),
            )
        if command == "history":
            orders = self.store.list_history_orders(limit=10)
            conditional = self.store.list_history_conditional_orders(limit=10)
            order_rows = [self._order_row_with_execution(row) for row in orders]
            conditional_rows = [dict(row) for row in conditional]
            return HandlerResponse(
                text=format_orders_summary(order_rows, conditional_rows, title="历史订单"),
                payload={"command": "history", "orders": order_rows, "conditional_orders": conditional_rows},
                reply_markup=self._orders_buttons(),
            )
        if command == "order":
            detail = self._order_detail(parsed["order_id"])
            return HandlerResponse(
                text=format_order_detail(detail),
                payload={"command": "order", "order_id": parsed["order_id"], "found": bool(detail)},
                reply_markup=self._order_detail_buttons(parsed["order_id"]) if detail else None,
            )
        if command == "balance":
            if self.balance_service is None:
                return HandlerResponse(text="余额服务未配置", payload={"command": "balance", "available": False})
            balance = self.balance_service.get_balance()
            return HandlerResponse(text=format_balance_summary(balance), payload={"command": "balance", "available": True, "balance": balance})
        if command == "quote":
            quote = self._quote(parsed)
            return HandlerResponse(
                text=format_quote_summary(
                    parsed["token_in"]["symbol"],
                    parsed["token_out"]["symbol"],
                    parsed["amount"],
                    quote,
                    token_out_decimals=int(parsed["token_out"]["decimals"]),
                ),
                payload={"command": "quote", "quote": quote},
            )
        if command == "copy_add":
            target = CopyTargetConfig(address=parsed["address"], status=CopyTargetStatus.PENDING_CONFIRMATION)
            self.store.create_or_update_copy_target(target)
            return HandlerResponse(
                text=format_copy_target_review(target),
                payload={"command": "copy_add", "address": target.address, "status": target.status.value},
                reply_markup=self._copy_review_buttons(target.address),
            )
        if command == "copy_confirm":
            return self._update_copy_target_status(parsed["address"], CopyTargetStatus.ACTIVE, "跟单已启用")
        if command == "copy_pause":
            return self._update_copy_target_status(parsed["address"], CopyTargetStatus.PAUSED, "跟单已暂停")
        if command == "copy_resume":
            return self._update_copy_target_status(parsed["address"], CopyTargetStatus.ACTIVE, "跟单已恢复")
        if command == "copy_remove":
            return self._update_copy_target_status(parsed["address"], CopyTargetStatus.REMOVED, "跟单已删除")
        if command == "copy_set":
            target = self.store.get_copy_target(parsed["address"])
            if target is None:
                return HandlerResponse(text=f"未找到跟单地址: {parsed['address']}", payload={"command": command, "status": "NOT_FOUND"})
            self.store.update_copy_target(
                parsed["address"],
                copy_ratio=parsed["copy_ratio"],
                max_copy_trade_usd=parsed["max_copy_trade_usd"],
            )
            updated = self.store.get_copy_target(parsed["address"])
            return HandlerResponse(
                text=format_copy_target_enabled(updated, title="跟单参数已更新"),
                payload={
                    "command": "copy_set",
                    "address": parsed["address"],
                    "status": updated.status.value,
                    "copy_ratio": str(updated.copy_ratio),
                    "max_copy_trade_usd": str(updated.max_copy_trade_usd),
                },
            )
        if command in {"copy_list", "copy_status"}:
            targets = self.store.list_copy_targets()
            events = [dict(row) for row in self.store.list_copy_trade_events(limit=3)]
            return HandlerResponse(
                text=format_copy_targets_summary(targets, events),
                payload={"command": command, "targets": len(targets), "events": len(events)},
                reply_markup=self._copy_list_buttons(),
            )
        return HandlerResponse(text="Unsupported command", payload=parsed)

    def _handle_order(self, order: MarketOrder | ConditionalOrder) -> HandlerResponse:
        if isinstance(order, MarketOrder):
            result = self.order_service.submit_market_order(order)
            return HandlerResponse(
                text=format_market_order_confirmation(order, result)
                if result.status == OrderStatus.PENDING_CONFIRMATION.value
                else self._format_order_result(result),
                payload={"order_id": result.order_id, "status": result.status},
                reply_markup=self._approval_buttons(result.order_id) if result.status == OrderStatus.PENDING_CONFIRMATION.value else None,
            )
        self.store.create_conditional_order(order, status=ConditionalOrderStatus.PENDING_CONFIRMATION)
        current_price = self._current_price(order)
        return HandlerResponse(
            text=format_conditional_order_summary(order, current_price),
            payload={
                "order_id": order.id,
                "status": ConditionalOrderStatus.PENDING_CONFIRMATION.value,
                "current_price_usd": str(current_price) if current_price is not None else None,
            },
            reply_markup=self._approval_buttons(order.id),
        )

    def _quote(self, parsed: dict[str, Any]) -> dict[str, Any]:
        token_in = parsed["token_in"]
        token_out = parsed["token_out"]
        amount_base_units = int(parsed["amount"] * (10 ** int(token_in["decimals"])))
        return self.order_service.quote_client.quote(
            chain_id=int(parsed["chain"]["chain_id"]),
            from_token_address=token_in["address"],
            to_token_address=token_out["address"],
            amount_base_units=amount_base_units,
            slippage_percent="1.0",
        )

    def _current_price(self, order: ConditionalOrder):
        if self.price_provider is None:
            return None
        try:
            return self.price_provider.get_price_usd(order.trigger.token.address)
        except Exception:
            return None

    def _is_authorized(self, actor: str, chat_id: str | None) -> bool:
        if self.allowed_user_ids and str(actor) not in self.allowed_user_ids:
            return False
        if self.allowed_chat_ids and str(chat_id or "") not in self.allowed_chat_ids:
            return False
        return True

    def _wallet_address(self) -> str | None:
        if self.balance_service is not None and hasattr(self.balance_service, "wallet_address"):
            return str(self.balance_service.wallet_address)
        return None

    def _order_row_with_execution(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        executions = self.store.get_executions(data["id"])
        for execution in reversed(executions):
            tx_hash = execution["tx_hash"]
            if tx_hash:
                data["last_tx_hash"] = tx_hash
                break
        return data

    def _order_detail(self, order_id: str) -> dict[str, Any]:
        order = self.store.get_order(order_id)
        if order is not None:
            return {
                "order": self._order_row_with_execution(order),
                "quotes": [dict(row) for row in self.store.get_quotes(order_id)],
                "risk_decisions": [dict(row) for row in self.store.get_risk_decisions(order_id)],
                "approvals": [dict(row) for row in self.store.get_approvals(order_id)],
                "executions": [dict(row) for row in self.store.get_executions(order_id)],
                "events": [dict(row) for row in self.store.get_events(order_id)],
            }
        conditional = self.store.get_conditional_order(order_id)
        if conditional is not None:
            return {
                "conditional_order": dict(conditional),
                "approvals": [dict(row) for row in self.store.get_approvals(order_id)],
                "events": [dict(row) for row in self.store.get_events(order_id)],
            }
        return {}

    def _confirm_conditional_order(self, row: Any, actor: str) -> HandlerResponse:
        order_id = row["id"]
        if row["status"] != ConditionalOrderStatus.PENDING_CONFIRMATION.value:
            return HandlerResponse(text=f"限价单当前不可确认: {row['status']}", payload={"order_id": order_id, "status": row["status"]})
        self.store.insert_approval(order_id, "CONFIRMED", actor)
        self.store.update_conditional_status(order_id, ConditionalOrderStatus.ACTIVE, {"confirmed_by": actor})
        return HandlerResponse(
            text=f"限价单已启用: {order_id}\n状态: watcher 将按条件监控触发",
            payload={"order_id": order_id, "status": ConditionalOrderStatus.ACTIVE.value},
            reply_markup=self._cancel_button(order_id),
        )

    def _reject_conditional_order(self, row: Any, actor: str) -> HandlerResponse:
        order_id = row["id"]
        self.store.insert_approval(order_id, "REJECTED", actor)
        self.store.update_conditional_status(order_id, ConditionalOrderStatus.CANCELLED, {"rejected_by": actor})
        return HandlerResponse(text=f"限价单已拒绝: {order_id}", payload={"order_id": order_id, "status": ConditionalOrderStatus.CANCELLED.value})

    def _update_copy_target_status(self, address: str, status: CopyTargetStatus, title: str) -> HandlerResponse:
        target = self.store.get_copy_target(address)
        if target is None:
            return HandlerResponse(text=f"未找到跟单地址: {address}", payload={"command": "copy_status", "address": address, "status": "NOT_FOUND"})
        self.store.update_copy_target(address, status=status)
        updated = self.store.get_copy_target(address)
        return HandlerResponse(
            text=format_copy_target_enabled(updated, title=title),
            payload={"command": "copy_status", "address": address, "status": updated.status.value},
            reply_markup=self._copy_list_buttons() if status != CopyTargetStatus.REMOVED else None,
        )

    @staticmethod
    def _approval_buttons(order_id: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "确认", "callback_data": f"confirm:{order_id}"},
                    {"text": "拒绝", "callback_data": f"reject:{order_id}"},
                ],
                [{"text": "取消", "callback_data": f"cancel:{order_id}"}],
            ]
        }

    @staticmethod
    def _copy_review_buttons(address: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "确认跟单", "callback_data": f"copy_confirm:{address}"},
                    {"text": "取消", "callback_data": f"copy_cancel:{address}"},
                ]
            ]
        }

    @staticmethod
    def _copy_list_buttons() -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": "刷新跟单", "callback_data": "nav:copy_status"}]]}

    @staticmethod
    def _cancel_button(order_id: str) -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": "取消", "callback_data": f"cancel:{order_id}"}]]}

    @staticmethod
    def _trade_type_buttons() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "买入", "callback_data": "trade:buy"},
                    {"text": "卖出", "callback_data": "trade:sell"},
                ],
                [
                    {"text": "限价买入", "callback_data": "trade:limit_buy"},
                    {"text": "限价卖出", "callback_data": "trade:limit_sell"},
                ],
            ]
        }

    @staticmethod
    def _guided_review_buttons() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "确认", "callback_data": "trade:confirm"},
                    {"text": "取消", "callback_data": "trade:cancel"},
                ]
            ]
        }

    @staticmethod
    def _home_buttons() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "流程交易", "callback_data": "trade:start"},
                    {"text": "当前订单", "callback_data": "nav:orders"},
                ],
                [
                    {"text": "历史订单", "callback_data": "nav:history"},
                    {"text": "跟单管理", "callback_data": "nav:copy_status"},
                ],
            ]
        }

    @staticmethod
    def _orders_buttons() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "刷新当前", "callback_data": "nav:orders"},
                    {"text": "历史订单", "callback_data": "nav:history"},
                ]
            ]
        }

    @staticmethod
    def _order_detail_buttons(order_id: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "刷新", "callback_data": f"order:{order_id}"},
                    {"text": "取消", "callback_data": f"cancel:{order_id}"},
                ],
                [{"text": "当前订单", "callback_data": "nav:orders"}],
            ]
        }

    def _format_order_result(self, result: OrderServiceResult, include_details: bool = False) -> str:
        if include_details:
            execution = self._latest_execution(result.order_id)
            quote = self._latest_quote(result.order_id)
            token_out = self._order_token_out(result.order_id)
            return format_execution_result(
                result,
                execution=execution,
                quote=quote,
                token_out_symbol=token_out.get("symbol") if token_out else None,
                token_out_decimals=int(token_out["decimals"]) if token_out and token_out.get("decimals") is not None else None,
            )
        if result.status == OrderStatus.PENDING_CONFIRMATION.value:
            return f"订单等待确认: {result.order_id}"
        if result.status == OrderStatus.SIGNED_NOT_BROADCASTED.value:
            if result.tracking_id:
                return f"订单已签名未广播: {result.order_id}\ntx hash: {result.tracking_id}"
            return f"订单已签名未广播: {result.order_id}"
        if result.status == OrderStatus.BROADCASTED.value:
            if result.tracking_id:
                return f"订单已广播: {result.order_id}\ntracking: {result.tracking_id}"
            return f"订单已广播: {result.order_id}"
        if result.status == OrderStatus.REJECTED_BY_USER.value:
            return f"订单已拒绝: {result.order_id}"
        if result.status == OrderStatus.FAILED.value:
            return f"订单失败: {result.reason}"
        return f"订单状态 {result.status}: {result.order_id}"

    def _latest_execution(self, order_id: str) -> dict[str, Any] | None:
        executions = self.store.get_executions(order_id)
        if not executions:
            return None
        return dict(executions[-1])

    def _latest_quote(self, order_id: str) -> dict[str, Any] | None:
        quotes = self.store.get_quotes(order_id)
        if not quotes:
            return None
        try:
            return json.loads(quotes[-1]["payload_json"])
        except Exception:
            return None

    def _order_token_out(self, order_id: str) -> dict[str, Any] | None:
        row = self.store.get_order(order_id)
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            return None
        token_out = payload.get("token_out") if isinstance(payload, dict) else None
        return token_out if isinstance(token_out, dict) else None
