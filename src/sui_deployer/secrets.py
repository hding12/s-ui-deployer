"""Secret generation and redaction helpers."""

from __future__ import annotations

import secrets
import string


PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
PATH_ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 20) -> str:
    """Generate a password with letters, digits, and special characters."""

    if length < 12:
        raise ValueError("password length must be at least 12")

    while True:
        password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in "!@#$%^&*()-_=+" for char in password)
        ):
            return password


def generate_path_segment(length: int = 24) -> str:
    """Generate an alphanumeric path segment for WebSocket or panel paths."""

    if length < 16:
        raise ValueError("path segment length must be at least 16")
    return "".join(secrets.choice(PATH_ALPHABET) for _ in range(length))
