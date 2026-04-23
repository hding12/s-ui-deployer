"""Remote backup workflow."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from sui_deployer.ssh import run_ssh


def run(values: dict[str, str], config_path: str) -> int:
    try:
        backup_path = create_remote_backup(values, config_path)
    except BackupError as exc:
        print(f"ERROR: 备份失败: {exc}")
        return 1
    print(f"OK: 远端备份已保存到 {backup_path}")
    return 0


class BackupError(RuntimeError):
    """Raised when a backup step fails."""


def create_remote_backup(values: dict[str, str], config_path: str) -> Path:
    site_dir = Path(config_path).parent
    backup_dir = site_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    site_id = values.get("SITE_ID", site_dir.name)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    remote_tar = f"/tmp/{site_id}-s-ui-backup-{stamp}.tar.gz"
    local_tar = backup_dir / f"{site_id}-s-ui-backup-{stamp}.tar.gz"

    cert_dir = _cert_parent(values)
    remote_command = (
        "set -eu; "
        f"sudo tar -czf {remote_tar} "
        "/usr/local/s-ui/db/s-ui.db "
        "/usr/local/s-ui/s-ui.service "
        "/usr/local/s-ui/s-ui.sh "
        f"{cert_dir} 2>/dev/null; "
        f"sudo chown {values.get('SSH_USER', 'ubuntu')}:{values.get('SSH_USER', 'ubuntu')} {remote_tar}"
    )
    result = run_ssh(values, remote_command, timeout=120)
    if result.returncode != 0:
        raise BackupError((result.stderr or result.stdout).strip())

    scp_cmd = [
        "scp",
        "-i",
        values["SSH_KEY_PATH"],
        "-P",
        values.get("SSH_PORT", "22"),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{values.get('SSH_USER', 'ubuntu')}@{values['VPS_HOST']}:{remote_tar}",
        str(local_tar),
    ]
    completed = subprocess.run(scp_cmd, check=False, text=True, capture_output=True, timeout=120)
    if completed.returncode != 0:
        raise BackupError((completed.stderr or completed.stdout).strip())

    run_ssh(values, f"rm -f {remote_tar}", timeout=30)
    return local_tar


def _cert_parent(values: dict[str, str]) -> str:
    cert_path = values.get("SSL_CERT_FULLCHAIN_PATH", "")
    if cert_path.startswith("/root/cert/"):
        return str(Path(cert_path).parent)
    return "/root/cert"
