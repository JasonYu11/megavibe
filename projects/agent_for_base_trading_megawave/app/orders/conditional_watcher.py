from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from app.core.order_info import ConditionalOrder
from app.core.order_state import ConditionalOrderStatus
from app.orders.order_service import OrderService, OrderServiceResult
from app.storage.sqlite_store import SQLiteStore


class PriceProvider(Protocol):
    def get_price_usd(self, token_address: str) -> Decimal:
        """Return current USD price for the given token."""


@dataclass
class TriggeredConditionalOrder:
    conditional_order_id: str
    current_price: Decimal
    market_order_id: str
    market_order_status: str
    tracking_id: str | None = None


@dataclass
class WatcherTickResult:
    checked: int
    triggered: int
    expired: int
    executions: list[OrderServiceResult]
    triggered_orders: list[TriggeredConditionalOrder] | None = None


@dataclass
class ConditionalOrderWatcher:
    store: SQLiteStore
    price_provider: PriceProvider
    order_service: OrderService

    def process_once(self) -> WatcherTickResult:
        checked = 0
        triggered = 0
        expired = 0
        executions: list[OrderServiceResult] = []
        triggered_orders: list[TriggeredConditionalOrder] = []

        for row in self.store.list_active_conditional_orders():
            checked += 1
            if row["status"] != ConditionalOrderStatus.ACTIVE.value:
                continue
            order = ConditionalOrder.from_dict(json.loads(row["payload_json"]))
            if self._is_expired(order):
                self.store.update_conditional_status(order.id, ConditionalOrderStatus.EXPIRED)
                expired += 1
                continue
            current_price = self.price_provider.get_price_usd(order.trigger.token.address)
            if self._matches(order.trigger.operator, current_price, order.trigger.target_price_usd):
                self.store.update_conditional_status(
                    order.id,
                    ConditionalOrderStatus.TRIGGERED,
                    {"current_price": str(current_price)},
                )
                market_order = order.build_market_order()
                result = self.order_service.submit_market_order(market_order)
                if result.status == "PENDING_CONFIRMATION":
                    result = self.order_service.confirm_order(result.order_id, actor="watcher")
                if result.status in {"DRY_RUN_COMPLETED", "BROADCASTED"}:
                    self.store.update_conditional_status(
                        order.id,
                        ConditionalOrderStatus.FILLED,
                        {"market_order_id": result.order_id, "market_order_status": result.status},
                    )
                elif result.status == "FAILED":
                    self.store.update_conditional_status(
                        order.id,
                        ConditionalOrderStatus.FAILED,
                        {"market_order_id": result.order_id, "market_order_status": result.status, "reason": result.reason},
                    )
                self.store.insert_event(
                    order.id,
                    "conditional_triggered_market_order",
                    {
                        "current_price": str(current_price),
                        "market_order_id": result.order_id,
                        "market_order_status": result.status,
                        "tracking_id": result.tracking_id,
                    },
                )
                executions.append(result)
                triggered_orders.append(
                    TriggeredConditionalOrder(
                        conditional_order_id=order.id,
                        current_price=current_price,
                        market_order_id=result.order_id,
                        market_order_status=result.status,
                        tracking_id=result.tracking_id,
                    )
                )
                triggered += 1

        return WatcherTickResult(
            checked=checked,
            triggered=triggered,
            expired=expired,
            executions=executions,
            triggered_orders=triggered_orders,
        )

    @staticmethod
    def _is_expired(order: ConditionalOrder) -> bool:
        expires_at = order.lifecycle.get("expires_at")
        if not expires_at:
            return False
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed <= datetime.now(UTC)

    @staticmethod
    def _matches(operator: str, current: Decimal, target: Decimal) -> bool:
        if operator == "<=":
            return current <= target
        if operator == "<":
            return current < target
        if operator == ">=":
            return current >= target
        if operator == ">":
            return current > target
        return False
