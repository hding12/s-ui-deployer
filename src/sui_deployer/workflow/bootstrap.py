"""Bootstrap workflow for installing S-UI."""

from __future__ import annotations

from sui_deployer.parser import parse_initial_admin
from sui_deployer.ssh import run_ssh


BOOTSTRAP_SCRIPT = r"""
set -euo pipefail

echo "== bootstrap: system dependencies =="
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  curl wget ca-certificates tar gzip unzip nano socat openssl

echo
echo "== bootstrap: root password =="
if [ -n "${ROOT_PASSWORD:-}" ]; then
  printf '%s\n' "root:${ROOT_PASSWORD}" | sudo chpasswd
  echo "root_password=set"
else
  echo "root_password=skipped"
fi

echo
echo "== bootstrap: s-ui install =="
curl -Ls https://raw.githubusercontent.com/alireza0/s-ui/master/install.sh -o /tmp/s-ui-install.sh
chmod 700 /tmp/s-ui-install.sh
# The installer may ask: Do you want to continue with the modification [y/n]?
# The documented answer for this project is n.
printf 'n\n' | sudo bash /tmp/s-ui-install.sh

echo
echo "== bootstrap: service =="
systemctl is-active s-ui.service 2>/dev/null || true
systemctl status s-ui.service --no-pager -l 2>/dev/null | sed -n '1,60p' || true

echo
echo "== bootstrap: admin show fallback =="
if [ -x /usr/local/s-ui/sui ]; then
  sudo /usr/local/s-ui/sui admin -show || true
elif command -v s-ui >/dev/null 2>&1; then
  sudo s-ui admin -show || true
fi
"""


def run(values: dict[str, str]) -> int:
    root_password = values.get("ROOT_PASSWORD", "")
    if not root_password:
        print("ERROR: ROOT_PASSWORD 为空，bootstrap 需要先生成或填写 root 密码")
        return 1

    command = (
        f"ROOT_PASSWORD={_shell_quote(root_password)} "
        f"bash -s <<'SUI_BOOTSTRAP'\n{BOOTSTRAP_SCRIPT}\nSUI_BOOTSTRAP"
    )
    result = run_ssh(values, command, timeout=900)

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())

    username, password = parse_initial_admin(result.stdout)
    if username or password:
        print()
        print("== parsed initial admin ==")
        if username:
            print(f"username={username}")
        if password:
            print("password=***REDACTED***")
            print("请把解析到的管理员密码写入 work/sites/<site-id>/site.env 或密码管理器。")
    else:
        print()
        print("WARN: 未能从输出解析管理员信息，请使用 admin -show fallback 输出或面板确认。")

    return result.returncode


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
