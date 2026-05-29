from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from app.copy_trading.action_builder import CopyTradeActionBuilder
from app.copy_trading.classifier import CopyTradeClassifier
from app.copy_trading.history_parser import DebankHistoryParser
from app.copy_trading.models import CopyActionStatus, CopyTargetConfig, CopyTargetStatus, CopyTradeAction, CopyTradeActionGroup, CopyTradeKind, CopyWatcherResult
from app.core.order_state import OrderStatus


@dataclass
class CopyTradeWatcher:
    store: Any
    debank_client: Any
    order_service: Any
    history_parser: DebankHistoryParser
    classifier: CopyTradeClassifier
    action_builder: CopyTradeActionBuilder
    page_count: int = 20
    live_copy_enabled: bool = False

    def process_once(self) -> CopyWatcherResult:
        targets: list[CopyTargetConfig] = self.store.list_copy_targets(status=CopyTargetStatus.ACTIVE)
        groups: list[CopyTradeActionGroup] = []
        processed = 0
        submitted = 0
        skipped = 0
        for target in targets:
            history = self.debank_client.get_user_history(target.address, chain_id=target.chain, page_count=self.page_count)
            parser = dataclasses.replace(self.history_parser, chain=target.chain, max_age_seconds=target.max_age_seconds)
            items = parser.parse(history)
            for item in sorted(items, key=lambda value: value.time_at):
                if self.store.is_copy_seen(target.address, item.history_id, item.tx_hash):
                    skipped += 1
                    continue
                intent = self.classifier.classify(item)
                if intent.kind in {CopyTradeKind.IGNORED, CopyTradeKind.COMPLEX}:
                    skipped += 1
                    self._record_seen_and_event(target, item.history_id, item.tx_hash, "SKIPPED", {"reason": intent.kind.value})
                    continue
                group = self.action_builder.build(target, intent)
                executed = self._submit_group(group)
                groups.append(executed)
                processed += 1
                submitted += sum(1 for action in executed.actions if action.status == CopyActionStatus.SUBMITTED)
                self._record_seen_and_event(target, item.history_id, item.tx_hash, "PROCESSED", self._group_payload(executed))
        return CopyWatcherResult(
            checked_targets=len(targets),
            processed_events=processed,
            submitted_orders=submitted,
            skipped_events=skipped,
            action_groups=groups,
        )

    def _submit_group(self, group: CopyTradeActionGroup) -> CopyTradeActionGroup:
        execution_mode = getattr(self.order_service, "execution_mode", "dry_run")
        if execution_mode not in {"dry_run", "live"}:
            return CopyTradeActionGroup(
                target=group.target,
                intent=group.intent,
                actions=[
                    dataclasses.replace(action, status=CopyActionStatus.FAILED, reason="copy_auto_execution_requires_dry_run_or_live")
                    if action.order is not None
                    else action
                    for action in group.actions
                ],
            )
        if execution_mode == "live" and not self.live_copy_enabled:
            return self._fail_group(group, "copy_live_disabled")
        if execution_mode == "live" and not getattr(self.order_service, "live_enabled", False):
            return self._fail_group(group, "copy_live_base_gate_disabled")
        actions: list[CopyTradeAction] = []
        for action in group.actions:
            if action.order is None or action.status in {CopyActionStatus.FAILED, CopyActionStatus.SKIPPED}:
                actions.append(action)
                continue
            try:
                result = self.order_service.submit_market_order(action.order)
                if result.status == OrderStatus.PENDING_CONFIRMATION.value:
                    result = self.order_service.confirm_order(result.order_id, actor="copy_watcher")
                action_status = CopyActionStatus.FAILED if result.status == OrderStatus.FAILED.value else CopyActionStatus.SUBMITTED
                actions.append(
                    dataclasses.replace(
                        action,
                        status=action_status,
                        order_id=result.order_id,
                        order_status=result.status,
                        reason=result.reason,
                    )
                )
            except Exception as exc:
                actions.append(dataclasses.replace(action, status=CopyActionStatus.FAILED, reason=str(exc)))
        return CopyTradeActionGroup(target=group.target, intent=group.intent, actions=actions)

    @staticmethod
    def _fail_group(group: CopyTradeActionGroup, reason: str) -> CopyTradeActionGroup:
        return CopyTradeActionGroup(
            target=group.target,
            intent=group.intent,
            actions=[
                dataclasses.replace(action, status=CopyActionStatus.FAILED, reason=reason)
                if action.order is not None
                else action
                for action in group.actions
            ],
        )

    def _record_seen_and_event(self, target: CopyTargetConfig, history_id: str, tx_hash: str, status: str, payload: dict[str, Any]) -> None:
        self.store.mark_copy_seen(target.address, history_id, tx_hash)
        self.store.insert_copy_trade_event(target.address, history_id, tx_hash, status, payload)

    @staticmethod
    def _group_payload(group: CopyTradeActionGroup) -> dict[str, Any]:
        return {
            "kind": group.intent.kind.value,
            "estimated_usd_value": str(group.intent.estimated_usd_value),
            "actions": [
                {
                    "side": action.side,
                    "token_in": action.token_in.symbol if action.token_in else None,
                    "token_out": action.token_out.symbol if action.token_out else None,
                    "amount": str(action.amount),
                    "status": action.status.value,
                    "reason": action.reason,
                    "order_id": action.order_id,
                    "order_status": action.order_status,
                }
                for action in group.actions
            ],
        }
