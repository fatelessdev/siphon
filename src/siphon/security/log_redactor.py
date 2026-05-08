from __future__ import annotations

import logging
import re

_SENSITIVE_KEYS = frozenset({
    "auth_token",
    "ct0",
    "cookie",
    "authorization",
    "x-csrf-token",
    "x-guest-token",
    "password",
    "token",
    "bearer",
    "secret",
    "api_key",
    "apikey",
})

_SENSITIVE_PATTERN = re.compile(
    r"(auth_token|ct0|cookie|authorization|x-csrf-token|x-guest-token"
    r"|bearer|password|token|secret|api_key)\s*[=:]\s*[\"']?(\S+)",
    re.IGNORECASE,
)

_SECRET_PATTERN = re.compile(
    r"^[A-Za-z0-9+/=_\-]{40,}$"  # Long alphanumeric strings that look like tokens
)


def mask_secret(value: str, keep: int = 4) -> str:
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep * 2) + value[-keep:]


def redact_string(text: str) -> str:
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        val = m.group(2)
        return f"{key}={mask_secret(val)}"

    return _SENSITIVE_PATTERN.sub(_replace, text)


def _looks_like_secret(value: str) -> bool:
    """Only flag values that look like actual tokens/secrets."""
    # Hex strings (auth_token, ct0 style)
    if re.match(r"^[a-f0-9]{40,}$", value):
        return True
    # Base64-ish tokens with no spaces or slashes
    if _SECRET_PATTERN.match(value):
        return True
    return False


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: mask_secret(v)
                    if isinstance(v, str) and k.lower() in _SENSITIVE_KEYS
                    else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    mask_secret(a) if isinstance(a, str) and _looks_like_secret(a) else a
                    for a in record.args
                )
        return True


def setup_redacted_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
