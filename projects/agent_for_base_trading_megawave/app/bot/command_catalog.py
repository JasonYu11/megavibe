from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.bot.command_parser import DEFAULT_BASE_TOKENS


class CommandCatalogError(ValueError):
    """Raised when a natural-language command cannot be normalized."""


@dataclass(frozen=True)
class NLCommandSpec:
    name: str
    risk: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


READ_ONLY_COMMANDS = (
    "help",
    "status",
    "mode",
    "balance",
    "orders",
    "history",
    "order",
    "copy_list",
    "copy_status",
)

BLOCKED_NL_COMMANDS = frozenset(
    {
        "confirm",
        "reject",
        "cancel",
        "copy_confirm",
        "copy_remove",
    }
)

BLOCKED_NL_PATTERNS = (
    re.compile(r"(^|\s)/(confirm|reject|cancel|copy_confirm|copy_remove)\b", re.IGNORECASE),
    re.compile(r"(确认|通过|批准).{0,12}(订单|ord_|cond_|交易)", re.IGNORECASE),
    re.compile(r"(拒绝|驳回).{0,12}(订单|ord_|cond_|交易)", re.IGNORECASE),
    re.compile(r"(取消|撤销).{0,12}(订单|ord_|cond_|交易)", re.IGNORECASE),
    re.compile(r"(删除|移除).{0,12}(跟单|copy|地址)", re.IGNORECASE),
)

NL_COMMAND_CATALOG: dict[str, NLCommandSpec] = {
    "help": NLCommandSpec("help", "read_only", "查看帮助"),
    "status": NLCommandSpec("status", "read_only", "查看运行状态"),
    "mode": NLCommandSpec("mode", "read_only", "查看执行模式"),
    "balance": NLCommandSpec("balance", "read_only", "查看钱包余额"),
    "orders": NLCommandSpec("orders", "read_only", "查看订单列表"),
    "history": NLCommandSpec("history", "read_only", "查看历史订单"),
    "order": NLCommandSpec("order", "read_only", "查看指定订单", required=("order_id",)),
    "copy_list": NLCommandSpec("copy_list", "read_only", "查看跟单地址列表"),
    "copy_status": NLCommandSpec("copy_status", "read_only", "查看跟单状态"),
    "quote": NLCommandSpec("quote", "quote", "查询兑换报价", required=("token_in", "token_out", "amount")),
    "buy": NLCommandSpec("buy", "trade_draft", "市价买入", required=("token_out", "amount"), optional=("token_in",)),
    "sell": NLCommandSpec("sell", "trade_draft", "市价卖出", required=("token_in", "amount"), optional=("token_out",)),
    "limit_buy": NLCommandSpec(
        "limit_buy",
        "trade_draft",
        "限价买入",
        required=("token_out", "amount", "target_price"),
        optional=("token_in",),
    ),
    "limit_sell": NLCommandSpec(
        "limit_sell",
        "trade_draft",
        "限价卖出",
        required=("token_in", "amount", "target_price"),
        optional=("token_out",),
    ),
}

TOKEN_ALIASES = {
    "u": "USDC",
    "usd": "USDC",
    "usdc": "USDC",
    "usdt": "USDC",
    "美元": "USDC",
    "eth": "ETH",
    "weth": "WETH",
    "virtual": "VIRTUAL",
    "virtuals": "VIRTUAL",
}

TOKEN_ADDRESS_RULES = (
    "Base 链使用 EVM 地址格式：合约地址必须是 42 个字符，必须以 0x 开头，"
    "后面正好跟 40 位十六进制字符 0-9/a-f/A-F。"
)


def is_blocked_nl_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in BLOCKED_NL_PATTERNS)


def normalize_intent(value: Any) -> str:
    intent = str(value or "").strip().lower().replace("-", "_")
    return intent[1:] if intent.startswith("/") else intent


def command_spec(intent: str) -> NLCommandSpec | None:
    return NL_COMMAND_CATALOG.get(normalize_intent(intent))


def resolve_token_address(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise CommandCatalogError("missing token")
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", text):
        return text.lower()
    if text.lower().startswith("0x"):
        raise CommandCatalogError(f"invalid token address: {text}. {TOKEN_ADDRESS_RULES}")
    if re.fullmatch(r"[a-fA-F0-9]{40}", text):
        raise CommandCatalogError(f"invalid token address: {text}. 合约地址缺少 0x 前缀。{TOKEN_ADDRESS_RULES}")
    symbol = TOKEN_ALIASES.get(text.lower(), text.upper())
    token = DEFAULT_BASE_TOKENS.tokens.get(symbol)
    if token:
        return str(token["address"]).lower()
    raise CommandCatalogError(f"unknown token: {text}")


def default_usdc_address() -> str:
    return str(DEFAULT_BASE_TOKENS.default_usdc()["address"]).lower()


def normalize_amount(value: Any, field_name: str = "amount") -> str:
    text = str(value or "").strip()
    if not text:
        raise CommandCatalogError(f"missing {field_name}")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        raise CommandCatalogError(f"invalid {field_name}: {value}")
    number = match.group(0)
    if number.startswith("-") or number.startswith("+"):
        raise CommandCatalogError(f"{field_name} must be positive")
    try:
        if Decimal(number) <= 0:
            raise CommandCatalogError(f"{field_name} must be positive")
    except InvalidOperation as exc:
        raise CommandCatalogError(f"invalid {field_name}: {value}") from exc
    return number


def public_catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "risk": spec.risk,
            "description": spec.description,
            "required": list(spec.required),
            "optional": list(spec.optional),
        }
        for spec in NL_COMMAND_CATALOG.values()
    ]


def nl_model_context() -> dict[str, Any]:
    return {
        "chain": "Base",
        "token_address_rules": TOKEN_ADDRESS_RULES,
        "known_symbol_aliases": TOKEN_ALIASES,
        "notes": [
            "VIRTUAL、USDC、USDT、U、美元等可作为别名；USDT/U/USD/美元 在本系统中按 USDC 处理。",
            "如果用户给出疑似合约地址但长度、0x 前缀或十六进制字符不符合规则，返回 status=clarification_required，并在 summary 中说明具体原因。",
            "不要从无效地址中抽取数字作为 amount；amount 必须由用户明确给出且大于 0。",
            "确认、拒绝、取消订单、删除跟单地址是手动禁区，不能映射成自然语言生成的命令。",
        ],
    }
