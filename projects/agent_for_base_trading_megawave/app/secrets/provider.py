from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

from dotenv import load_dotenv


class SecretError(RuntimeError):
    """Raised when a secret reference cannot be resolved."""


class SecretProvider(Protocol):
    def resolve(self, secret_ref: str) -> str:
        """Resolve a secret reference to its value."""


@dataclass(frozen=True)
class EnvSecretProvider:
    env_path: str | None = ".env"

    def resolve(self, secret_ref: str) -> str:
        if not secret_ref.startswith("ENV:"):
            raise SecretError("EnvSecretProvider only supports ENV: refs")
        if self.env_path:
            load_dotenv(self.env_path, override=False)
        name = secret_ref.split(":", 1)[1]
        value = os.environ.get(name)
        if not value:
            raise SecretError(f"missing environment secret: {name}")
        return value


@dataclass(frozen=True)
class KeychainSecretProvider:
    def resolve(self, secret_ref: str) -> str:
        if not secret_ref.startswith("KEYCHAIN:"):
            raise SecretError("KeychainSecretProvider only supports KEYCHAIN: refs")
        payload = secret_ref.split(":", 1)[1]
        parts = payload.split(":")
        if len(parts) == 1:
            account = None
            service = parts[0]
        elif len(parts) == 2:
            account, service = parts
        else:
            raise SecretError("invalid KEYCHAIN ref; use KEYCHAIN:service or KEYCHAIN:account:service")

        cmd = ["security", "find-generic-password"]
        if account:
            cmd.extend(["-a", account])
        cmd.extend(["-s", service, "-w"])

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise SecretError("macOS security command not available") from exc
        except subprocess.CalledProcessError as exc:
            raise SecretError(f"missing keychain secret: {service}") from exc

        value = result.stdout.strip()
        if not value:
            raise SecretError(f"empty keychain secret: {service}")
        return value


@dataclass(frozen=True)
class CompositeSecretProvider:
    env_provider: EnvSecretProvider = EnvSecretProvider()
    keychain_provider: KeychainSecretProvider = KeychainSecretProvider()

    def resolve(self, secret_ref: str) -> str:
        if secret_ref.startswith("ENV:"):
            return self.env_provider.resolve(secret_ref)
        if secret_ref.startswith("KEYCHAIN:"):
            return self.keychain_provider.resolve(secret_ref)
        raise SecretError("unsupported secret ref scheme")

