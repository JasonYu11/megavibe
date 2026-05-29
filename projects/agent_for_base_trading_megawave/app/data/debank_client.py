from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from app.secrets.provider import SecretProvider


class DebankClientError(RuntimeError):
    """Raised when a DeBank request fails."""


@dataclass
class DebankClient:
    access_key_ref: str
    secret_provider: SecretProvider
    base_url: str = "https://pro-openapi.debank.com/v1"
    session: requests.Session = field(default_factory=requests.Session)
    timeout: int = 30

    def _headers(self) -> dict[str, str]:
        access_key = self.secret_provider.resolve(self.access_key_ref)
        return {"accept": "application/json", "AccessKey": access_key}

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise DebankClientError(f"debank request failed: {path}") from exc
        except ValueError as exc:
            raise DebankClientError(f"debank invalid json: {path}") from exc

    def get_user_history(self, address: str, chain_id: str = "base", page_count: int = 20) -> dict[str, Any]:
        data = self._get(
            "/user/history_list",
            {"id": address, "chain_id": chain_id, "page_count": page_count},
        )
        if not isinstance(data, dict):
            raise DebankClientError("unexpected user history response")
        return data

    def get_token_info(self, token_address: str, chain_id: str = "base") -> dict[str, Any]:
        data = self._get("/token/list_by_ids", {"chain_id": chain_id, "ids": token_address})
        if isinstance(data, list) and data:
            return data[0]
        raise DebankClientError("token not found")

    def get_token_price(self, token_address: str, chain_id: str = "base") -> str | None:
        info = self.get_token_info(token_address, chain_id=chain_id)
        price = info.get("price")
        return None if price is None else str(price)

    def get_top_holders(self, token_address: str, chain_id: str = "base", limit: int = 10) -> list[Any]:
        data = self._get(
            "/token/top_holders",
            {"chain_id": chain_id, "id": token_address, "start": 0, "limit": min(limit, 100)},
        )
        if not isinstance(data, list):
            raise DebankClientError("unexpected top holders response")
        return data

    def get_user_token_list(self, address: str, chain_id: str = "base", is_all: bool = True) -> list[dict[str, Any]]:
        data = self._get("/user/token_list", {"id": address, "chain_id": chain_id, "is_all": str(is_all).lower()})
        if not isinstance(data, list):
            raise DebankClientError("unexpected token list response")
        return data

    def get_user_chain_balance(self, address: str, chain_id: str = "base") -> dict[str, Any]:
        data = self._get("/user/chain_balance", {"id": address, "chain_id": chain_id})
        if not isinstance(data, dict):
            raise DebankClientError("unexpected chain balance response")
        return data

    @staticmethod
    def parse_history_transfers(history_response: dict[str, Any]) -> list[dict[str, Any]]:
        history_list = history_response.get("history_list") or []
        token_dict = history_response.get("token_dict") or {}
        parsed: list[dict[str, Any]] = []
        for item in history_list:
            sends = item.get("sends") or []
            receives = item.get("receives") or []
            parsed.append(
                {
                    "id": item.get("id"),
                    "time_at": item.get("time_at"),
                    "cate_id": item.get("cate_id"),
                    "sends": sends,
                    "receives": receives,
                    "token_dict": token_dict,
                }
            )
        return parsed

