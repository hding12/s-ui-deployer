"""OpenSSH/scp wrapper helpers."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class SSHResult:
    returncode: int
    stdout: str
    stderr: str


def run_ssh(values: dict[str, str], remote_command: str, timeout: int = 30) -> SSHResult:
    """Run a read-only command through OpenSSH."""

    host = values["VPS_HOST"]
    user = values.get("SSH_USER", "ubuntu")
    port = values.get("SSH_PORT", "22")
    key_path = values["SSH_KEY_PATH"]

    cmd = [
        "ssh",
        "-i",
        key_path,
        "-p",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        remote_command,
    ]
    completed = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return SSHResult(completed.returncode, completed.stdout, completed.stderr)
