from __future__ import annotations

import re
import secrets

# Crockford base32 without 0/1/I/L/O/U so codes read aloud and typed by hand stay unambiguous.
JOIN_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
JOIN_CODE_LENGTH = 6
_SEPARATORS = re.compile(r"[\s-]+")


def generate_join_code() -> str:
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


def normalize_join_code(value: str) -> str:
    """Canonicalize user input such as ``k7q-4pm`` to ``K7Q4PM``; raise if malformed."""

    candidate = _SEPARATORS.sub("", value).upper()
    if len(candidate) != JOIN_CODE_LENGTH or any(
        char not in JOIN_CODE_ALPHABET for char in candidate
    ):
        raise ValueError("join codes are six letters and digits, like K7Q-4PM")
    return candidate


def format_join_code(code: str) -> str:
    return f"{code[:3]}-{code[3:]}"
