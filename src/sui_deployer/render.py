"""Template rendering helpers."""

from __future__ import annotations


SENSITIVE_KEY_PARTS = (
    "PASSWORD",
    "TOKEN",
    "PRIVATE",
    "SECRET",
    "UUID",
)


def redact_config(values: dict[str, str]) -> dict[str, str]:
    """Return a redacted copy of config values for logs and plans."""

    redacted: dict[str, str] = {}
    for key, value in values.items():
        if any(part in key for part in SENSITIVE_KEY_PARTS) and value:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted
