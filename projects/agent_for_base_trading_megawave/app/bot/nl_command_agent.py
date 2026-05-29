from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import ssl
from typing import Any, Protocol
import urllib.error
import urllib.request

from dotenv import load_dotenv

from app.bot.command_catalog import (
    BLOCKED_NL_COMMANDS,
    CommandCatalogError,
    command_spec,
    default_usdc_address,
    is_blocked_nl_text,
    normalize_amount,
    normalize_intent,
    nl_model_context,
    public_catalog_payload,
    resolve_token_address,
)
from app.bot.command_parser import CommandParseError, TelegramCommandParser


class NLCommandClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        ...


class DeepSeekConfigError(RuntimeError):
    """Raised when the DeepSeek client cannot be configured."""


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 20, max_retries: int = 1) -> None:
        if not api_key:
            raise DeepSeekConfigError("DEEPSEEK_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "DeepSeekClient":
        load_dotenv(env_path, override=False)
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout_seconds=int(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.environ.get("DEEPSEEK_MAX_RETRIES", "1")),
        )

    def complete_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=ssl.create_default_context()) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:300]
                raise RuntimeError(f"DeepSeek {purpose} request failed with HTTP {exc.code}: {body}") from exc
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise RuntimeError(f"DeepSeek {purpose} request failed: {exc}") from exc
        else:
            raise RuntimeError(f"DeepSeek {purpose} request failed: {last_error}")

        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        return _json_object(content)


@dataclass(frozen=True)
class NLCommandResult:
    status: str
    intent: str | None = None
    command: str | None = None
    risk: str | None = None
    summary: str = ""
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    parsed_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "intent": self.intent,
            "command": self.command,
            "risk": self.risk,
            "summary": self.summary,
            "missing_fields": self.missing_fields,
            "warnings": self.warnings,
            "confidence": self.confidence,
            "parsed_type": self.parsed_type,
        }


class NLCommandAgent:
    def __init__(
        self,
        parser: TelegramCommandParser | None = None,
        client: NLCommandClient | None = None,
        *,
        enable_review: bool = True,
    ) -> None:
        self.parser = parser or TelegramCommandParser()
        self.client = client
        self.enable_review = enable_review

    def parse(self, text: str) -> NLCommandResult:
        prompt = str(text or "").strip()
        if not prompt:
            return NLCommandResult(status="clarification_required", summary="请输入要转换的自然语言指令。", missing_fields=["text"])
        if is_blocked_nl_text(prompt):
            return self._blocked()

        deterministic = _deterministic_payload(prompt)
        if deterministic is not None:
            return self._build_result(deterministic)

        try:
            intent_payload = self._intent(prompt)
        except DeepSeekConfigError as exc:
            return NLCommandResult(status="configuration_error", summary=str(exc))
        except Exception as exc:
            return NLCommandResult(status="error", summary=str(exc))

        result = self._build_result(intent_payload)
        if result.status == "mapped" and self.enable_review and result.risk in {"trade_draft", "quote"}:
            result = self._review(prompt, result)
        return result

    def _intent(self, text: str) -> dict[str, Any]:
        client = self.client or DeepSeekClient.from_env()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是交易系统的自然语言槽位提取器。只输出 JSON object，不要输出 Markdown。"
                    "你不能执行命令，只能识别意图和字段。"
                    "禁止把确认、拒绝、取消订单、删除跟单地址映射成命令。"
                    "如果缺少字段，返回 status=clarification_required 和 missing_fields。"
                    "必须理解 Base/EVM 合约地址规则和错误理由: "
                    + json.dumps(nl_model_context(), ensure_ascii=False)
                    + "。"
                    "可用命令目录: "
                    + json.dumps(public_catalog_payload(), ensure_ascii=False)
                    + "。字段名只使用 intent, status, confidence, slots, missing_fields, summary。"
                ),
            },
            {"role": "user", "content": text},
        ]
        return client.complete_json(messages, purpose="intent")

    def _build_result(self, payload: dict[str, Any]) -> NLCommandResult:
        status = str(payload.get("status") or "mapped")
        intent = normalize_intent(payload.get("intent") or payload.get("command"))
        if intent in BLOCKED_NL_COMMANDS:
            return self._blocked(intent=intent)
        if status == "blocked_manual_only":
            return self._blocked(intent=intent or None)
        if status == "clarification_required":
            return NLCommandResult(
                status="clarification_required",
                intent=intent or None,
                summary=str(payload.get("summary") or "还需要补充必要字段。"),
                missing_fields=[str(item) for item in payload.get("missing_fields") or []],
                confidence=_confidence(payload),
            )

        spec = command_spec(intent)
        if spec is None:
            return NLCommandResult(
                status="unmapped",
                intent=intent or None,
                summary="无法安全映射到当前命令白名单。",
                confidence=_confidence(payload),
            )

        slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
        try:
            command = self._command_from_slots(spec.name, slots)
        except CommandCatalogError as exc:
            missing = _missing_fields_from_error(str(exc), spec.required)
            return NLCommandResult(
                status="clarification_required",
                intent=spec.name,
                risk=spec.risk,
                summary=str(exc),
                missing_fields=missing,
                confidence=_confidence(payload),
            )

        try:
            parsed = self.parser.parse(command)
        except CommandParseError as exc:
            return NLCommandResult(
                status="invalid_command",
                intent=spec.name,
                command=command,
                risk=spec.risk,
                summary=f"命令未通过现有解析器校验：{exc}",
                confidence=_confidence(payload),
            )

        return NLCommandResult(
            status="mapped",
            intent=spec.name,
            command=command,
            risk=spec.risk,
            summary=str(payload.get("summary") or spec.description),
            warnings=_risk_warnings(spec.risk),
            confidence=_confidence(payload),
            parsed_type=parsed.__class__.__name__ if not isinstance(parsed, dict) else str(parsed.get("command") or "dict"),
        )

    def _command_from_slots(self, intent: str, slots: dict[str, Any]) -> str:
        if intent in {"help", "status", "mode", "balance", "orders", "history", "copy_list", "copy_status"}:
            return f"/{intent}"
        if intent == "order":
            order_id = str(slots.get("order_id") or "").strip()
            if not order_id:
                raise CommandCatalogError("missing order_id")
            return f"/order {order_id}"
        if intent == "quote":
            return (
                f"/quote {resolve_token_address(slots.get('token_in'))} "
                f"{resolve_token_address(slots.get('token_out'))} "
                f"{normalize_amount(slots.get('amount'))}"
            )
        if intent == "buy":
            command = f"/buy {resolve_token_address(slots.get('token_out'))} {normalize_amount(slots.get('amount'))}"
            token_in = _optional_token(slots.get("token_in"))
            if token_in and token_in != default_usdc_address():
                command += f" --with {token_in}"
            return command
        if intent == "sell":
            command = f"/sell {resolve_token_address(slots.get('token_in'))} {normalize_amount(slots.get('amount'))}"
            token_out = _optional_token(slots.get("token_out"))
            if token_out and token_out != default_usdc_address():
                command += f" --to {token_out}"
            return command
        if intent == "limit_buy":
            command = (
                f"/limit_buy {resolve_token_address(slots.get('token_out'))} "
                f"{normalize_amount(slots.get('amount'))} at {normalize_amount(slots.get('target_price'), 'target_price')}"
            )
            token_in = _optional_token(slots.get("token_in"))
            if token_in and token_in != default_usdc_address():
                command += f" --with {token_in}"
            return command
        if intent == "limit_sell":
            command = (
                f"/limit_sell {resolve_token_address(slots.get('token_in'))} "
                f"{normalize_amount(slots.get('amount'))} at {normalize_amount(slots.get('target_price'), 'target_price')}"
            )
            token_out = _optional_token(slots.get("token_out"))
            if token_out and token_out != default_usdc_address():
                command += f" --to {token_out}"
            return command
        raise CommandCatalogError(f"unsupported intent: {intent}")

    def _review(self, original_text: str, result: NLCommandResult) -> NLCommandResult:
        client = self.client or DeepSeekClient.from_env()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是命令审查器。只输出 JSON object。检查标准命令是否忠实于原始自然语言、是否触及手动确认禁区。"
                    "如果安全，输出 {\"approved\": true, \"warnings\": [], \"summary\": \"...\"}。"
                    "如果不安全，输出 {\"approved\": false, \"warnings\": [\"...\"], \"summary\": \"...\"}。"
                ),
            },
            {"role": "user", "content": json.dumps({"text": original_text, "command": result.command, "intent": result.intent}, ensure_ascii=False)},
        ]
        try:
            review = client.complete_json(messages, purpose="review")
        except Exception as exc:
            warnings = [*result.warnings, f"LLM 审查失败，已保留解析器校验结果：{exc}"]
            return _replace_result(result, warnings=warnings)
        if review.get("approved") is False:
            return NLCommandResult(
                status="blocked_manual_only" if result.intent in BLOCKED_NL_COMMANDS else "unmapped",
                intent=result.intent,
                command=None,
                risk=result.risk,
                summary=str(review.get("summary") or "审查未通过。"),
                warnings=[str(item) for item in review.get("warnings") or []],
                confidence=result.confidence,
            )
        warnings = [*result.warnings, *[str(item) for item in review.get("warnings") or []]]
        summary = str(review.get("summary") or result.summary)
        return _replace_result(result, warnings=warnings, summary=summary)

    @staticmethod
    def _blocked(intent: str | None = None) -> NLCommandResult:
        return NLCommandResult(
            status="blocked_manual_only",
            intent=intent,
            summary="确认、拒绝、取消订单以及删除跟单地址必须手动点击按钮或输入精确命令，不能由自然语言生成。",
            warnings=["manual_action_required"],
        )


def _optional_token(value: Any) -> str | None:
    text = str(value or "").strip()
    return resolve_token_address(text) if text else None


def _json_object(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model did not return a JSON object")
        data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model JSON response must be an object")
    return data


def _confidence(payload: dict[str, Any]) -> float | None:
    if payload.get("confidence") is None:
        return None
    try:
        return float(payload["confidence"])
    except (TypeError, ValueError):
        return None


def _missing_fields_from_error(message: str, defaults: tuple[str, ...]) -> list[str]:
    if message.startswith("missing "):
        return [message.removeprefix("missing ").strip()]
    if message.startswith("amount must be positive"):
        return ["amount"]
    if message.startswith("target_price must be positive"):
        return ["target_price"]
    if message.startswith("unknown token") or message.startswith("invalid"):
        return []
    return list(defaults)


def _risk_warnings(risk: str) -> list[str]:
    if risk == "trade_draft":
        return ["将创建待确认订单，仍需要手动确认后才会执行。"]
    if risk == "quote":
        return ["仅查询报价，不创建订单。"]
    return []


def _replace_result(result: NLCommandResult, **changes: Any) -> NLCommandResult:
    data = result.to_dict()
    data.update(changes)
    return NLCommandResult(**data)


def _deterministic_payload(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    compact = lowered.replace(" ", "")
    if "copy_status" in lowered or ("跟单" in text and ("状态" in text or "运行" in text)):
        return _payload("copy_status", "查看跟单状态")
    if "copy_list" in lowered or ("跟单" in text and ("地址" in text or "列表" in text or "有哪些" in text)):
        return _payload("copy_list", "查看跟单地址列表")
    if "/help" in lowered or "帮助" in text or "怎么使用" in text or "如何使用" in text or "命令说明" in text:
        return _payload("help", "查看帮助")
    if "/status" in lowered or "系统状态" in text or "是否正常" in text or compact in {"状态", "查看状态"}:
        return _payload("status", "查看运行状态")
    if "/mode" in lowered or "dryrun" in compact or "live" in lowered or "执行模式" in text or "模式" in text:
        return _payload("mode", "查看执行模式")
    if "/balance" in lowered or "余额" in text:
        return _payload("balance", "查看钱包余额")
    order_match = re.search(r"\b(?:ord|cond)_[A-Za-z0-9_-]+\b", text)
    if order_match and ("查" in text or "看" in text or "详情" in text or "/order" in lowered):
        return {
            "status": "mapped",
            "intent": "order",
            "confidence": 1.0,
            "slots": {"order_id": order_match.group(0)},
            "summary": "查看订单详情",
        }
    if "/orders" in lowered or "当前订单" in text or "所有订单" in text or "订单列表" in text:
        return _payload("orders", "查看订单列表")
    if "/history" in lowered or "历史" in text or "记录" in text:
        return _payload("history", "查看历史记录")
    trade = _deterministic_trade_payload(text)
    if trade is not None:
        return trade
    return None


def _payload(intent: str, summary: str) -> dict[str, Any]:
    return {"status": "mapped", "intent": intent, "confidence": 1.0, "slots": {}, "summary": summary}


_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TOKEN_ALIAS_RE = re.compile(r"(?<![A-Za-z])(?:virtuals?|usdc|usdt|eth|weth|u|美元)(?![A-Za-z])", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?")
_STABLE_TOKENS = {"u", "usd", "usdc", "usdt", "美元"}


def _deterministic_trade_payload(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    tokens = _extract_tokens(text)
    numbers = _extract_numbers(text)
    if not numbers:
        return None

    if "报价" in text or "quote" in lowered or ("换" in text and ("多少" in text or "价格" in text)):
        token_in, token_out = _quote_tokens(tokens)
        if token_out:
            return _trade_payload(
                "quote",
                {"token_in": token_in, "token_out": token_out, "amount": numbers[0]},
                f"查询 {token_out} 报价",
            )

    is_limit_buy = ("买" in text or "buy" in lowered) and _contains_any(text, ("低于", "跌到", "小于", "少于", "below"))
    is_limit_sell = ("卖" in text or "sell" in lowered) and _contains_any(text, ("涨到", "高于", "达到", "大于", "above"))
    if is_limit_buy and len(numbers) >= 2:
        token = _first_risky_token(tokens)
        if token:
            return _trade_payload(
                "limit_buy",
                {"token_out": token, "amount": numbers[1], "target_price": numbers[0], "token_in": "USDC"},
                f"限价买入 {token}",
            )
    if is_limit_sell and len(numbers) >= 2:
        token = _first_risky_token(tokens)
        if token:
            return _trade_payload(
                "limit_sell",
                {"token_in": token, "amount": numbers[1], "target_price": numbers[0], "token_out": "USDC"},
                f"限价卖出 {token}",
            )

    if "买" in text or "buy" in lowered:
        token = _first_risky_token(tokens)
        if token:
            return _trade_payload("buy", {"token_out": token, "amount": numbers[0], "token_in": "USDC"}, f"市价买入 {token}")
    if "卖" in text or "sell" in lowered:
        token = _first_risky_token(tokens)
        if token:
            return _trade_payload("sell", {"token_in": token, "amount": numbers[0], "token_out": "USDC"}, f"市价卖出 {token}")
    return None


def _trade_payload(intent: str, slots: dict[str, str], summary: str) -> dict[str, Any]:
    return {"status": "mapped", "intent": intent, "confidence": 1.0, "slots": slots, "summary": summary}


def _extract_tokens(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for match in _ADDRESS_RE.finditer(text):
        found.append((match.start(), match.group(0)))
    for match in _TOKEN_ALIAS_RE.finditer(text):
        found.append((match.start(), match.group(0).upper()))
    return [value for _, value in sorted(found, key=lambda item: item[0])]


def _extract_numbers(text: str) -> list[str]:
    address_spans = [match.span() for match in _ADDRESS_RE.finditer(text)]
    numbers: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        if any(start <= match.start() < end for start, end in address_spans):
            continue
        numbers.append(match.group(0))
    return numbers


def _quote_tokens(tokens: list[str]) -> tuple[str, str | None]:
    if not tokens:
        return "USDC", None
    if len(tokens) == 1:
        token = tokens[0]
        return ("USDC", token) if _is_risky_token(token) else (token, None)
    return tokens[0], _first_risky_token(tokens[1:]) or tokens[1]


def _first_risky_token(tokens: list[str]) -> str | None:
    for token in tokens:
        if _is_risky_token(token):
            return token
    return None


def _is_risky_token(token: str) -> bool:
    value = token.lower()
    return bool(_ADDRESS_RE.fullmatch(token)) or value not in _STABLE_TOKENS


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)
