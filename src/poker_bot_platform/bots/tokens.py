from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


def generate_bearer_token() -> str:
    """Generate the registration secret that is displayed to the owner once."""

    return secrets.token_urlsafe(32)


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class EncryptedTokenStore:
    """Small encryption boundary for values persisted by the account layer."""

    _fernet: Fernet

    @classmethod
    def from_deployment_secret(cls, secret: str | bytes) -> EncryptedTokenStore:
        raw = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(raw) < 32:
            raise ValueError("deployment secret must contain at least 32 bytes")
        key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return cls(Fernet(key))

    def encrypt(self, token: str) -> str:
        if not token:
            raise ValueError("token cannot be empty")
        return self._fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("stored bot token cannot be decrypted") from exc

    def matches(self, ciphertext: str, presented_token: str) -> bool:
        try:
            expected = self.decrypt(ciphertext)
        except ValueError:
            return False
        return secrets.compare_digest(expected, presented_token)
