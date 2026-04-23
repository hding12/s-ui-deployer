"""Read-only diagnosis workflow."""

from __future__ import annotations

from sui_deployer.ssh import run_ssh


DIAGNOSE_COMMAND = r"""
set -u
echo "== system =="
uname -a
if command -v lsb_release >/dev/null 2>&1; then lsb_release -a 2>/dev/null; fi
echo
echo "== user =="
id
echo
echo "== sudo =="
sudo -n true >/dev/null 2>&1 && echo "sudo_nopasswd=ok" || echo "sudo_nopasswd=not_available"
echo
echo "== s-ui =="
command -v s-ui || true
systemctl is-active s-ui.service 2>/dev/null || true
systemctl is-enabled s-ui.service 2>/dev/null || true
sudo -n test -d /usr/local/s-ui && echo "/usr/local/s-ui exists" || echo "/usr/local/s-ui missing"
sudo -n test -f /usr/local/s-ui/db/s-ui.db && echo "s-ui.db exists" || echo "s-ui.db missing"
echo
echo "== firewall =="
if command -v ufw >/dev/null 2>&1; then sudo -n ufw status 2>/dev/null || ufw status 2>/dev/null || true; else echo "ufw not installed"; fi
echo
echo "== dns =="
echo "domain=${DOMAIN:-}"
echo "expected_ipv4=${VPS_HOST:-}"
if [ -n "${DOMAIN:-}" ]; then
  if command -v getent >/dev/null 2>&1; then
    getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | sed 's/^/resolved_ipv4=/'
  else
    python3 - "$DOMAIN" <<'PY' 2>/dev/null || true
import socket
import sys
for item in sorted({info[4][0] for info in socket.getaddrinfo(sys.argv[1], 80, socket.AF_INET)}):
    print(f"resolved_ipv4={item}")
PY
  fi
fi
echo
echo "== listening =="
ss -lntup 2>/dev/null | sed -n '1,80p' || true
"""


def run(values: dict[str, str]) -> int:
    command = (
        f"DOMAIN={_shell_quote(values.get('DOMAIN', ''))} "
        f"VPS_HOST={_shell_quote(values.get('VPS_HOST', ''))} "
        f"bash -s <<'SUI_DIAGNOSE'\n{DIAGNOSE_COMMAND}\nSUI_DIAGNOSE"
    )
    result = run_ssh(values, command, timeout=45)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
