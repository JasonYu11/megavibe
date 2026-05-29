from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_account import Account

from app.secrets.provider import SecretProvider


@dataclass(frozen=True)
class SignedTransaction:
    raw_transaction_hex: str
    transaction_hash: str
    signer_address: str


@dataclass(frozen=True)
class LocalSigner:
    secret_provider: SecretProvider
    wallet_secret_refs: dict[str, str]

    def get_address(self, wallet_id: str) -> str:
        if wallet_id not in self.wallet_secret_refs:
            raise KeyError(f"unknown wallet_id: {wallet_id}")

        private_key = self.secret_provider.resolve(self.wallet_secret_refs[wallet_id])
        try:
            return Account.from_key(private_key).address
        finally:
            private_key = ""

    def sign_transaction(self, wallet_id: str, tx: dict[str, Any]) -> SignedTransaction:
        if wallet_id not in self.wallet_secret_refs:
            raise KeyError(f"unknown wallet_id: {wallet_id}")

        private_key = self.secret_provider.resolve(self.wallet_secret_refs[wallet_id])
        try:
            account = Account.from_key(private_key)
            signed = Account.sign_transaction(tx, private_key)
            raw_hex = signed.raw_transaction.hex()
            if not raw_hex.startswith("0x"):
                raw_hex = "0x" + raw_hex
            tx_hash = signed.hash.hex()
            if not tx_hash.startswith("0x"):
                tx_hash = "0x" + tx_hash
            return SignedTransaction(
                raw_transaction_hex=raw_hex,
                transaction_hash=tx_hash,
                signer_address=account.address,
            )
        finally:
            private_key = ""

    @staticmethod
    def recover_signer(raw_transaction_hex: str) -> str:
        return Account.recover_transaction(raw_transaction_hex)
