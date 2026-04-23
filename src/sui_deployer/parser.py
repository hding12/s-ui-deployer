"""Parsers for S-UI install output and command output."""

from __future__ import annotations

import re


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def parse_initial_admin(output: str) -> tuple[str | None, str | None]:
    """Parse initial S-UI admin username/password from install output."""

    clean_output = ANSI_RE.sub("", output)
    username = _find_value(clean_output, ("username", "user", "admin username"))
    password = _find_value(clean_output, ("password", "admin password"))
    return username, password


def _find_value(output: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}\s*[:=]\s*(\S+)", re.IGNORECASE)
        match = pattern.search(output)
        if match:
            return match.group(1).strip()
    return None
