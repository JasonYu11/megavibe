from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests

from app.secrets.provider import SecretProvider


class OkxClientError(RuntimeError):
    """Raised when an OKX request fails."""


@dataclass
class OkxDexClient:
    api_key_ref: str
    secret_key_ref: str
    passphrase_ref: str
    project_id_ref: str
    secret_provider: SecretProvider
    base_url: str = "https://web3.okx.com"
    session: requests.Session = field(default_factory=requests.Session)
    timeout: int = 30

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _headers(self, method: str, path: str, query: str = "", body: str = "") -> dict[str, str]:
        api_key = self.secret_provider.resolve(self.api_key_ref)
        secret_key = self.secret_provider.resolve(self.secret_key_ref)
        passphrase = self.secret_provider.resolve(self.passphrase_ref)
        project_id = self.secret_provider.resolve(self.project_id_ref)
        ts = self._timestamp()
        prehash = ts + method.upper() + path + (query or body)
        digest = hmac.new(secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        return {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": base64.b64encode(digest).decode("utf-8"),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "OK-ACCESS-PROJECT": project_id,
        }

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = "?" + urlencode(params)
        headers = self._headers("GET", path, query=query)
        try:
            response = self.session.get(
                self.base_url.rstrip("/") + path,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise OkxClientError(f"okx request failed: {path}") from exc
        except ValueError as exc:
            raise OkxClientError(f"okx invalid json: {path}") from exc
        if not isinstance(data, dict):
            raise OkxClientError(f"unexpected okx response: {path}")
        return data

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = self._headers("POST", path, body=body_str)
        try:
            response = self.session.post(
                self.base_url.rstrip("/") + path,
                data=body_str,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise OkxClientError(f"okx request failed: {path}") from exc
        except ValueError as exc:
            raise OkxClientError(f"okx invalid json: {path}") from exc
        if not isinstance(data, dict):
            raise OkxClientError(f"unexpected okx response: {path}")
        return data

    def quote(
        self,
        chain_id: int,
        from_token_address: str,
        to_token_address: str,
        amount_base_units: int,
        slippage_percent: str,
    ) -> dict[str, Any]:
        return self._get(
            "/api/v6/dex/aggregator/quote",
            {
                "chainIndex": str(chain_id),
                "fromTokenAddress": from_token_address,
                "toTokenAddress": to_token_address,
                "amount": str(amount_base_units),
                "slippage": str(slippage_percent),
            },
        )

    def swap(
        self,
        chain_id: int,
        from_token_address: str,
        to_token_address: str,
        amount_base_units: int,
        slippage_percent: str,
        user_wallet_address: str,
    ) -> dict[str, Any]:
        return self._get(
            "/api/v6/dex/aggregator/swap",
            {
                "chainIndex": str(chain_id),
                "fromTokenAddress": from_token_address,
                "toTokenAddress": to_token_address,
                "amount": str(amount_base_units),
                "slippagePercent": str(slippage_percent),
                "userWalletAddress": user_wallet_address,
            },
        )

    def approve_transaction(self, chain_id: int, token_address: str, approve_amount: int) -> dict[str, Any]:
        return self._get(
            "/api/v6/dex/aggregator/approve-transaction",
            {
                "chainIndex": str(chain_id),
                "tokenContractAddress": token_address,
                "approveAmount": str(approve_amount),
            },
        )

    def broadcast(self, chain_id: int, signed_tx: str, address: str, enable_mev_protection: bool = True) -> dict[str, Any]:
        return self._post(
            "/api/v6/dex/pre-transaction/broadcast-transaction",
            {
                "chainIndex": str(chain_id),
                "signedTx": signed_tx,
                "address": address,
                "extraData": json.dumps({"enableMevProtection": bool(enable_mev_protection)}),
            },
        )

    def get_order_status(self, chain_id: int, order_id: str, address: str) -> dict[str, Any]:
        return self._get(
            "/api/v6/dex/post-transaction/orders",
            {"chainIndex": str(chain_id), "orderId": order_id, "address": address, "limit": "1"},
        )
