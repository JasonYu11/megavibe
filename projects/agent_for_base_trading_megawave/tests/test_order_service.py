from __future__ import annotations

import json
from decimal import Decimal

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.orders.order_service import OrderService
from app.risk.context import SQLiteRiskContextProvider
from app.risk.risk_engine import RiskEngine
from app.signing.local_signer import LocalSigner
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import market_payload
from tests.test_risk_engine import policy
from eth_account import Account


class FakeQuoteClient:
    def __init__(self):  # type: ignore[no-untyped-def]
        self.calls = []

    def quote(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return {"priceImpactPercent": "0.1", "isHoneyPot": False, "taxRate": {"buyTaxRate": "0", "sellTaxRate": "0"}}


class UnavailableQuoteClient(FakeQuoteClient):
    def quote(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return {"code": "82000", "data": [], "msg": "Insufficient liquidity"}


class StaticSecretProvider:
    def __init__(self, private_key: str) -> None:
        self.private_key = private_key

    def resolve(self, secret_ref: str) -> str:
        assert secret_ref == "TEST:PRIVATE_KEY"
        return self.private_key


class StaticBalanceProvider:
    def __init__(self, amount: str) -> None:
        self.amount = Decimal(amount)

    def get_token_balance(self, token):  # type: ignore[no-untyped-def]
        return self.amount


class FakeExecutionClient(FakeQuoteClient):
    def __init__(self) -> None:
        super().__init__()
        self.swap_calls = []
        self.broadcast_calls = []

    def swap(self, **kwargs):  # type: ignore[no-untyped-def]
        self.swap_calls.append(kwargs)
        return {
            "data": [
                {
                    "tx": {
                        "nonce": "0x0",
                        "type": "0x2",
                        "gasPrice": "0x1",
                        "maxFeePerGas": "0x2",
                        "maxPriorityFeePerGas": "0x1",
                        "gas": "0x5208",
                        "to": "0x000000000000000000000000000000000000dEaD",
                        "value": "0x0",
                        "data": "0x",
                        "maxSpendAmount": "",
                    }
                }
            ]
        }

    def broadcast(self, **kwargs):  # type: ignore[no-untyped-def]
        self.broadcast_calls.append(kwargs)
        return {"code": "0", "data": [{"orderId": "okx_order_1"}]}

    def approve_transaction(self, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "code": "0",
            "data": [
                {
                    "dexContractAddress": "0x000000000000000000000000000000000000dEaD",
                    "data": "0x095ea7b3",
                    "gasLimit": "50000",
                }
            ],
        }


class InvalidTxExecutionClient(FakeExecutionClient):
    def __init__(self, tx: dict) -> None:
        super().__init__()
        self.tx = tx

    def swap(self, **kwargs):  # type: ignore[no-untyped-def]
        self.swap_calls.append(kwargs)
        return {"data": [{"tx": self.tx}]}


class NoBroadcastIdExecutionClient(FakeExecutionClient):
    def broadcast(self, **kwargs):  # type: ignore[no-untyped-def]
        self.broadcast_calls.append(kwargs)
        return {"code": "0", "data": [{}]}


class FailingSigner:
    def sign_transaction(self, wallet_id: str, tx: dict):  # type: ignore[no-untyped-def]
        raise RuntimeError("signer failed")


class FakeRpcResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def market_payload_with_wallet_address(address: str) -> dict:
    payload = market_payload()
    payload["wallet"] = {"wallet_id": "base_main_test", "address": address}
    return payload


def test_market_order_dry_run_reaches_pending_confirmation_without_sign_or_broadcast(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    quote_client = FakeQuoteClient()
    service = OrderService(store, RiskEngine(policy()), quote_client, execution_mode="dry_run")
    order = MarketOrder.from_dict(market_payload())

    result = service.submit_market_order(order)
    row = store.get_order(order.id)

    assert result.status == OrderStatus.PENDING_CONFIRMATION.value
    assert row is not None
    assert row["status"] == OrderStatus.PENDING_CONFIRMATION.value
    assert quote_client.calls[0]["amount_base_units"] == 2_000_000
    assert store.get_quotes(order.id)
    assert store.get_risk_decisions(order.id)[0]["decision"] == "APPROVED"


def test_market_order_dry_run_rejected_by_risk(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    payload = market_payload()
    payload["amount"]["value"] = "10"
    order = MarketOrder.from_dict(payload)

    result = service.submit_market_order(order)
    row = store.get_order(order.id)

    assert result.status == OrderStatus.FAILED.value
    assert result.reason == "max_single_trade_usd"
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value


def test_order_service_passes_risk_context_provider_to_risk_engine(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(
        store,
        RiskEngine(policy()),
        FakeQuoteClient(),
        execution_mode="dry_run",
        risk_context_provider=lambda order: {"wallet_balances": {order.token_in.address.lower(): "1"}},
    )
    order = MarketOrder.from_dict(market_payload())

    result = service.submit_market_order(order)
    row = store.get_order(order.id)

    assert result.status == OrderStatus.FAILED.value
    assert result.reason == "insufficient_balance"
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value


def test_order_service_rejects_when_sqlite_daily_context_exceeds_limit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    previous = MarketOrder.from_dict({**market_payload(), "id": "ord_previous"})
    store.create_order(previous)
    store.update_order_status(previous.id, OrderStatus.FILLED)
    risk_policy = policy()
    risk_policy["risk"]["max_daily_trade_usd"] = 3
    service = OrderService(
        store,
        RiskEngine(risk_policy),
        FakeQuoteClient(),
        execution_mode="dry_run",
        risk_context_provider=SQLiteRiskContextProvider(store),
    )
    order = MarketOrder.from_dict(market_payload())

    result = service.submit_market_order(order)

    assert result.status == OrderStatus.FAILED.value
    assert result.reason == "max_daily_trade_usd"


def test_order_service_clamps_exact_in_amount_to_available_balance_before_quote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    quote_client = FakeQuoteClient()
    service = OrderService(
        store,
        RiskEngine(policy()),
        quote_client,
        execution_mode="dry_run",
        balance_provider=StaticBalanceProvider("2.1234567"),
    )
    payload = market_payload()
    payload["amount"]["value"] = "4"
    order = MarketOrder.from_dict(payload)

    result = service.submit_market_order(order)
    row = store.get_order(order.id)
    events = [row for row in store.get_events(order.id) if row["event_type"] == "order_amount_clamped_to_balance"]
    event_payload = json.loads(events[0]["payload_json"])

    assert result.status == OrderStatus.PENDING_CONFIRMATION.value
    assert quote_client.calls[0]["amount_base_units"] == 2_123_456
    assert row is not None
    assert json.loads(row["payload_json"])["amount"]["value"] == "2.123456"
    assert event_payload["requested_amount"] == "4"
    assert event_payload["adjusted_amount"] == "2.123456"


def test_order_service_rejects_unavailable_okx_quote_before_confirmation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    quote_client = UnavailableQuoteClient()
    service = OrderService(store, RiskEngine(policy()), quote_client, execution_mode="dry_run")
    order = MarketOrder.from_dict(market_payload())

    result = service.submit_market_order(order)
    row = store.get_order(order.id)

    assert result.status == OrderStatus.FAILED.value
    assert result.reason == "quote_unavailable: 82000 Insufficient liquidity"
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value


def test_order_service_rejects_zero_available_balance_before_creating_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(
        store,
        RiskEngine(policy()),
        FakeQuoteClient(),
        execution_mode="dry_run",
        balance_provider=StaticBalanceProvider("0"),
    )
    order = MarketOrder.from_dict(market_payload())

    try:
        service.submit_market_order(order)
    except ValueError as exc:
        assert "insufficient_balance" in str(exc)
    else:
        raise AssertionError("zero balance should fail before quote")

    assert store.get_order(order.id) is None


def test_live_order_rejects_unresolved_token_metadata_before_quote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    quote_client = FakeQuoteClient()
    service = OrderService(store, RiskEngine(policy()), quote_client, execution_mode="live", live_enabled=True)
    payload = market_payload()
    unresolved = "0x1111111111111111111111111111111111111111"
    payload["token_out"] = {"symbol": unresolved, "address": unresolved, "decimals": 18}
    order = MarketOrder.from_dict(payload)

    try:
        service.submit_market_order(order)
    except ValueError as exc:
        assert "live token metadata unresolved" in str(exc)
    else:
        raise AssertionError("expected unresolved live token to fail")

    assert quote_client.calls == []
    assert store.get_order(order.id) is None


def test_confirm_order_sign_only_signs_but_does_not_broadcast(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = FakeExecutionClient()
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="sign_only",
        execution_client=execution_client,
        signer=signer,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    submitted = service.submit_market_order(order)
    assert submitted.status == OrderStatus.PENDING_CONFIRMATION.value

    result = service.confirm_order(order.id, actor="tester")
    row = store.get_order(order.id)
    approvals = store.get_approvals(order.id)

    assert result.status == OrderStatus.SIGNED_NOT_BROADCASTED.value
    assert result.tracking_id
    assert row is not None
    assert row["status"] == OrderStatus.SIGNED_NOT_BROADCASTED.value
    assert approvals[0]["decision"] == "CONFIRMED"
    assert execution_client.swap_calls
    assert execution_client.broadcast_calls == []


def test_confirm_order_rejects_swap_tx_missing_required_fields_before_signing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = InvalidTxExecutionClient({"to": "0x000000000000000000000000000000000000dEaD", "value": "0x0"})
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="sign_only",
        execution_client=execution_client,
        signer=signer,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    try:
        service.confirm_order(order.id, actor="tester")
    except RuntimeError as exc:
        assert "swap tx missing required fields" in str(exc)
    else:
        raise AssertionError("invalid swap tx should fail before signing")

    row = store.get_order(order.id)
    executions = store.get_executions(order.id)
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value
    assert executions[-1]["status"] == OrderStatus.FAILED.value
    assert "swap tx missing required fields" in executions[-1]["payload_json"]
    assert execution_client.broadcast_calls == []


def test_confirm_order_rejects_swap_tx_chain_mismatch_before_signing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = InvalidTxExecutionClient(
        {
            "nonce": "0x0",
            "gasPrice": "0x1",
            "gas": "0x5208",
            "chainId": "0x1",
            "to": "0x000000000000000000000000000000000000dEaD",
            "value": "0x0",
            "data": "0x",
        }
    )
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="sign_only",
        execution_client=execution_client,
        signer=signer,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    try:
        service.confirm_order(order.id, actor="tester")
    except RuntimeError as exc:
        assert "swap tx chainId mismatch" in str(exc)
    else:
        raise AssertionError("wrong chainId should fail before signing")

    row = store.get_order(order.id)
    executions = store.get_executions(order.id)
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value
    assert executions[-1]["status"] == OrderStatus.FAILED.value
    assert "swap tx chainId mismatch" in executions[-1]["payload_json"]
    assert execution_client.broadcast_calls == []


def test_confirm_order_records_signer_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = FakeExecutionClient()
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="sign_only",
        execution_client=execution_client,
        signer=FailingSigner(),
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    try:
        service.confirm_order(order.id, actor="tester")
    except RuntimeError as exc:
        assert "signer failed" in str(exc)
    else:
        raise AssertionError("signer failure should be recorded and re-raised")

    row = store.get_order(order.id)
    executions = store.get_executions(order.id)
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value
    assert executions[-1]["status"] == OrderStatus.FAILED.value
    assert "signer failed" in executions[-1]["payload_json"]
    assert execution_client.broadcast_calls == []


def test_live_mode_requires_explicit_enable_before_broadcast(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = FakeExecutionClient()
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="live",
        execution_client=execution_client,
        signer=signer,
        live_enabled=False,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    try:
        service.confirm_order(order.id, actor="tester")
    except RuntimeError as exc:
        assert "live execution is disabled" in str(exc)
    else:
        raise AssertionError("live mode without live_enabled should fail")

    row = store.get_order(order.id)
    assert row is not None
    assert row["status"] == OrderStatus.PENDING_CONFIRMATION.value
    assert execution_client.broadcast_calls == []


def test_live_mode_broadcasts_only_when_explicitly_enabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = FakeExecutionClient()
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="live",
        execution_client=execution_client,
        signer=signer,
        live_enabled=True,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    result = service.confirm_order(order.id, actor="tester")
    row = store.get_order(order.id)

    assert result.status == OrderStatus.BROADCASTED.value
    assert result.tracking_id == "okx_order_1"
    assert row is not None
    assert row["status"] == OrderStatus.BROADCASTED.value
    assert execution_client.broadcast_calls


def test_swap_tx_gas_limit_uses_buffer_and_legacy_floor(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service = OrderService(
        SQLiteStore(tmp_path / "orders.sqlite"),
        RiskEngine(policy()),
        FakeQuoteClient(),
        gas_limit_multiplier=Decimal("1.5"),
        min_swap_gas_limit=3_000_000,
        max_swap_gas_limit=5_000_000,
    )

    tx = service._apply_gas_limit_buffer({"gas": 1_038_000})

    assert tx["gas"] == 3_000_000


def test_swap_tx_gas_limit_respects_cap(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service = OrderService(
        SQLiteStore(tmp_path / "orders.sqlite"),
        RiskEngine(policy()),
        FakeQuoteClient(),
        gas_limit_multiplier=Decimal("2"),
        min_swap_gas_limit=3_000_000,
        max_swap_gas_limit=5_000_000,
    )

    tx = service._apply_gas_limit_buffer({"gas": 4_000_000})

    assert tx["gas"] == 5_000_000


def test_live_mode_approves_erc20_before_swap_when_allowance_is_low(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_post(url, json, timeout):  # type: ignore[no-untyped-def]
        if json["method"] == "eth_call":
            return FakeRpcResponse({"result": "0x0"})
        if json["method"] == "eth_getTransactionCount":
            return FakeRpcResponse({"result": "0x0"})
        if json["method"] == "eth_getTransactionReceipt":
            return FakeRpcResponse({"result": {"transactionHash": json["params"][0], "status": "0x1"}})
        raise AssertionError(f"unexpected RPC method: {json['method']}")

    monkeypatch.setattr("app.orders.order_service.requests.post", fake_post)
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = FakeExecutionClient()
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="live",
        execution_client=execution_client,
        signer=signer,
        live_enabled=True,
        rpc_url="https://base.rpc.test",
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    result = service.confirm_order(order.id, actor="tester")
    executions = store.get_executions(order.id)

    assert result.status == OrderStatus.BROADCASTED.value
    assert len(execution_client.broadcast_calls) == 2
    assert executions[-2]["status"] == "APPROVAL_FILLED"
    assert executions[-1]["status"] == OrderStatus.BROADCASTED.value


def test_approve_tx_is_sent_to_token_contract_not_spender(tmp_path) -> None:  # type: ignore[no-untyped-def]
    token_address = "0xde61878b0b21ce395266c44d4d548d1c72a3eb07"
    spender = "0x000000000000000000000000000000000000dEaD"
    service = OrderService(
        SQLiteStore(tmp_path / "orders.sqlite"),
        RiskEngine(policy()),
        FakeQuoteClient(),
    )

    tx = service._build_approve_tx(
        chain_id=8453,
        token_address=token_address,
        approve_item={"dexContractAddress": spender, "data": "0x095ea7b3", "gasLimit": "50000"},
        swap_tx={"gasPrice": "0x1"},
        nonce=7,
    )

    assert tx["to"] == "0xde61878b0b21ce395266c44D4d548D1C72A3eB07"
    assert tx["to"] != spender
    assert tx["gas"] == 300_000


def test_swap_tx_to_address_is_normalized_to_checksum_before_signing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    service = OrderService(
        SQLiteStore(tmp_path / "orders.sqlite"),
        RiskEngine(policy()),
        FakeQuoteClient(),
    )

    tx = {"to": "0x16332535e2c27da578bc2e82beb09ce9d3c8eb07", "data": "0x", "value": 0, "gas": 21_000, "chainId": 8453, "gasPrice": 1}
    normalized = {k: service._normalize_tx_value(k, v) for k, v in tx.items()}
    normalized["to"] = service._checksum_address(normalized["to"])

    assert normalized["to"] == "0x16332535E2c27da578bC2e82bEb09Ce9d3C8EB07"


def test_live_mode_requires_broadcast_tracking_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    store = SQLiteStore(tmp_path / "orders.sqlite")
    execution_client = NoBroadcastIdExecutionClient()
    signer = LocalSigner(StaticSecretProvider(account.key.hex()), {"base_main_test": "TEST:PRIVATE_KEY"})
    service = OrderService(
        store,
        RiskEngine(policy()),
        execution_client,
        execution_mode="live",
        execution_client=execution_client,
        signer=signer,
        live_enabled=True,
    )
    order = MarketOrder.from_dict(market_payload_with_wallet_address(account.address))
    service.submit_market_order(order)

    try:
        service.confirm_order(order.id, actor="tester")
    except RuntimeError as exc:
        assert "broadcast response does not contain tx hash or order id" in str(exc)
    else:
        raise AssertionError("broadcast response without tracking id should fail")

    row = store.get_order(order.id)
    executions = store.get_executions(order.id)
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value
    assert executions[-1]["status"] == OrderStatus.FAILED.value
    assert "broadcast response does not contain tx hash or order id" in executions[-1]["payload_json"]


def test_reject_order_persists_approval_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    order = MarketOrder.from_dict(market_payload())
    service.submit_market_order(order)

    result = service.reject_order(order.id, actor="tester")
    row = store.get_order(order.id)
    approvals = store.get_approvals(order.id)

    assert result.status == OrderStatus.REJECTED_BY_USER.value
    assert row is not None
    assert row["status"] == OrderStatus.REJECTED_BY_USER.value
    assert approvals[0]["decision"] == "REJECTED"
