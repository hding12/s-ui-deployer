"""Certificate issuance workflow."""

from __future__ import annotations

from sui_deployer.ssh import run_ssh


ISSUE_CERT_SCRIPT = r"""
set -euo pipefail

domain="${DOMAIN}"
port="${SSL_HTTP_PORT:-80}"
cert_dir="/root/cert/${domain}"
fullchain="${cert_dir}/fullchain.pem"
privkey="${cert_dir}/privkey.pem"

echo "== issue-cert: precheck =="
echo "domain=${domain}"
echo "http_port=${port}"
if [ -f "$fullchain" ] && [ -f "$privkey" ]; then
  echo "cert_status=exists"
  openssl x509 -in "$fullchain" -noout -subject -issuer -dates || true
  exit 0
fi

echo
echo "== issue-cert: s-ui ssl menu =="
# S-UI's SSL menu calls acme.sh. acme.sh refuses to run when SUDO_* variables
# are present, so the caller must invoke this script under a clean root env.
printf '19\n1\n%s\n%s\n' "$domain" "$port" | s-ui

echo
echo "== issue-cert: verify =="
test -f "$fullchain"
test -f "$privkey"
chmod 755 "$fullchain" "$privkey"
openssl x509 -in "$fullchain" -noout -subject -issuer -dates
echo "fullchain=${fullchain}"
echo "privkey=${privkey}"
"""


def run(values: dict[str, str]) -> int:
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空，无法申请证书")
        return 1

    port = values.get("SSL_HTTP_PORT", "80")
    command = (
        "sudo env -u SUDO_USER -u SUDO_UID -u SUDO_GID -u SUDO_COMMAND "
        f"HOME=/root DOMAIN={_shell_quote(domain)} SSL_HTTP_PORT={_shell_quote(port)} "
        f"bash -s <<'SUI_ISSUE_CERT'\n{ISSUE_CERT_SCRIPT}\nSUI_ISSUE_CERT"
    )
    result = run_ssh(values, command, timeout=900)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
