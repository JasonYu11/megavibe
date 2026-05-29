from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from app.core.order_info import ConditionalOrder, MarketOrder, OrderValidationError


class CommandParseError(ValueError):
    """Raised when a Telegram command cannot be parsed."""


@dataclass(frozen=True)
class TokenRegistry:
    tokens: dict[str, dict]

    def default_usdc(self) -> dict:
        return self.tokens["USDC"]

    def resolve_address(self, address: str) -> dict:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
            raise CommandParseError(f"token address required: {address}")
        normalized = address.lower()
        for token in self.tokens.values():
            if token["address"].lower() == normalized:
                return token
        return {"symbol": address, "address": address, "decimals": 18}


DEFAULT_BASE_TOKENS = TokenRegistry(
    {
        "USDC": {
            "symbol": "USDC",
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6,
        },
        "ETH": {
            "symbol": "ETH",
            "address": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            "decimals": 18,
        },
        "WETH": {
            "symbol": "WETH",
            "address": "0x4200000000000000000000000000000000000006",
            "decimals": 18,
        },
        "VIRTUAL": {
            "symbol": "VIRTUAL",
            "address": "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
            "decimals": 18,
        },
    }
)


@dataclass(frozen=True)
class TelegramCommandParser:
    token_registry: TokenRegistry = DEFAULT_BASE_TOKENS
    wallet_id: str = "base_main_test"
    wallet_address: str | None = None
    token_resolver: object | None = None

    def parse(self, text: str) -> MarketOrder | ConditionalOrder | dict:
        parts = text.strip().split()
        if not parts:
            raise CommandParseError("empty command")
        command = parts[0].lower()
        if command == "/buy":
            return self._parse_buy(parts)
        if command == "/sell":
            return self._parse_sell(parts)
        if command == "/quote":
            return self._parse_quote(parts)
        if command == "/limit_buy":
            return self._parse_limit_order(parts, side="buy")
        if command == "/limit_sell":
            return self._parse_limit_order(parts, side="sell")
        if command in {"/start", "/help", "/status", "/mode", "/balance", "/orders", "/history"}:
            return {"command": command[1:]}
        if command in {"/copy_list", "/copy_status"}:
            if len(parts) != 1:
                raise CommandParseError(f"{command} does not accept arguments")
            return {"command": command[1:]}
        if command in {"/copy_add", "/copy_confirm", "/copy_pause", "/copy_resume", "/copy_remove"}:
            if len(parts) != 2:
                raise CommandParseError(f"{command} requires ADDRESS")
            address = self._address(parts[1])
            return {"command": command[1:], "address": address}
        if command == "/copy_set":
            if len(parts) != 6 or parts[2].lower() != "ratio" or parts[4].lower() != "max":
                raise CommandParseError("/copy_set ADDRESS ratio 0.00001 max 0.01")
            address = self._address(parts[1])
            return {
                "command": "copy_set",
                "address": address,
                "copy_ratio": self._amount(parts[3], "copy_ratio"),
                "max_copy_trade_usd": self._amount(parts[5], "max_copy_trade_usd"),
            }
        if command == "/order":
            if len(parts) != 2:
                raise CommandParseError("/order requires ORDER_ID")
            return {"command": "order", "order_id": parts[1]}
        if command in {"/confirm", "/reject", "/cancel"}:
            if len(parts) != 2:
                raise CommandParseError(f"{command} requires ORDER_ID")
            return {"command": command[1:], "order_id": parts[1]}
        raise CommandParseError(f"unknown command: {command}")

    def _chain(self) -> dict:
        return {"namespace": "evm", "chain_id": 8453, "chain_name": "base"}

    def _wallet(self) -> dict:
        wallet = {"wallet_id": self.wallet_id}
        if self.wallet_address:
            wallet["address"] = self.wallet_address
        return wallet

    def _token(self, address: str) -> dict:
        if self.token_resolver is not None:
            try:
                return self.token_resolver.resolve(address)  # type: ignore[attr-defined]
            except Exception as exc:
                raise CommandParseError(str(exc)) from exc
        return self.token_registry.resolve_address(address)

    @staticmethod
    def _address(address: str) -> str:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
            raise CommandParseError(f"address required: {address}")
        return address.lower()

    @staticmethod
    def _amount(text: str, field_name: str = "amount") -> Decimal:
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise CommandParseError(f"invalid {field_name}: {text}") from exc
        if not amount.is_finite() or amount <= 0:
            raise CommandParseError(f"{field_name} must be positive")
        return amount

    @staticmethod
    def _build_market_order(payload: dict) -> MarketOrder:
        try:
            return MarketOrder.from_dict(payload)
        except OrderValidationError as exc:
            raise CommandParseError(str(exc)) from exc

    @staticmethod
    def _build_conditional_order(payload: dict) -> ConditionalOrder:
        try:
            return ConditionalOrder.from_dict(payload)
        except OrderValidationError as exc:
            raise CommandParseError(str(exc)) from exc

    def _parse_buy(self, parts: list[str]) -> MarketOrder:
        if len(parts) not in {3, 5}:
            raise CommandParseError("/buy TOKEN_OUT_ADDRESS AMOUNT [--with TOKEN_IN_ADDRESS]")
        out_token = self._token(parts[1])
        amount = self._amount(parts[2])
        in_token = self.token_registry.default_usdc()
        if len(parts) == 5:
            if parts[3] != "--with":
                raise CommandParseError("/buy TOKEN_OUT_ADDRESS AMOUNT [--with TOKEN_IN_ADDRESS]")
            in_token = self._token(parts[4])
        return self._build_market_order(
            {
                "order_type": "market",
                "source": "telegram_command",
                "chain": self._chain(),
                "wallet": self._wallet(),
                "token_in": in_token,
                "token_out": out_token,
                "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                "trade": {"side": "buy", "route_provider": "okx", "execution_mode": "immediate"},
                "approval": {"require_confirmation": True, "confirmation_channel": "telegram"},
            }
        )

    def _parse_sell(self, parts: list[str]) -> MarketOrder:
        if len(parts) not in {3, 5}:
            raise CommandParseError("/sell TOKEN_IN_ADDRESS AMOUNT [--to TOKEN_OUT_ADDRESS]")
        in_token = self._token(parts[1])
        amount = self._amount(parts[2])
        out_token = self.token_registry.default_usdc()
        if len(parts) == 5:
            if parts[3] != "--to":
                raise CommandParseError("/sell TOKEN_IN_ADDRESS AMOUNT [--to TOKEN_OUT_ADDRESS]")
            out_token = self._token(parts[4])
        return self._build_market_order(
            {
                "order_type": "market",
                "source": "telegram_command",
                "chain": self._chain(),
                "wallet": self._wallet(),
                "token_in": in_token,
                "token_out": out_token,
                "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                "trade": {"side": "sell", "route_provider": "okx", "execution_mode": "immediate"},
                "approval": {"require_confirmation": True, "confirmation_channel": "telegram"},
            }
        )

    def _parse_quote(self, parts: list[str]) -> dict:
        if len(parts) != 4:
            raise CommandParseError("/quote TOKEN_IN_ADDRESS TOKEN_OUT_ADDRESS AMOUNT")
        return {
            "command": "quote",
            "token_in": self._token(parts[1]),
            "token_out": self._token(parts[2]),
            "amount": self._amount(parts[3]),
            "chain": self._chain(),
        }

    def _parse_limit_order(self, parts: list[str], side: str) -> ConditionalOrder:
        usage = (
            "/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE [--with TOKEN_IN_ADDRESS]"
            if side == "buy"
            else "/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE [--to TOKEN_OUT_ADDRESS]"
        )
        if len(parts) not in {5, 7} or parts[3].lower() != "at":
            raise CommandParseError(usage)
        token = self._token(parts[1])
        amount = self._amount(parts[2])
        target_price = self._amount(parts[4], "target_price")

        if side == "buy":
            in_token = self.token_registry.default_usdc()
            out_token = token
            operator = "<="
            override_flag = "--with"
            if len(parts) == 7:
                if parts[5] != override_flag:
                    raise CommandParseError(usage)
                in_token = self._token(parts[6])
        else:
            in_token = token
            out_token = self.token_registry.default_usdc()
            operator = ">="
            override_flag = "--to"
            if len(parts) == 7:
                if parts[5] != override_flag:
                    raise CommandParseError(usage)
                out_token = self._token(parts[6])

        return self._build_conditional_order(
            {
                "order_type": "conditional",
                "source": "telegram_command",
                "chain": self._chain(),
                "wallet": self._wallet(),
                "trigger": {
                    "type": "price",
                    "source": "debank",
                    "token": out_token if side == "buy" else in_token,
                    "operator": operator,
                    "target_price_usd": str(target_price),
                    "poll_interval_seconds": 30,
                },
                "action": {
                    "order_type": "market",
                    "token_in": in_token,
                    "token_out": out_token,
                    "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                    "trade": {"side": side, "route_provider": "okx"},
                },
                "approval": {
                    "require_confirmation_on_create": False,
                    "require_confirmation_on_trigger": True,
                    "confirmation_channel": "telegram",
                },
                "lifecycle": {"status": "active"},
            }
        )
