"""Configure S-UI admin password and basic panel settings."""

from __future__ import annotations

from sui_deployer.ssh import run_ssh


CONFIGURE_PANEL_SCRIPT = r"""
set -euo pipefail

echo "== configure-panel: admin password =="
if [ -n "${SUI_ADMIN_USERNAME:-}" ] && [ -n "${SUI_ADMIN_PASSWORD:-}" ]; then
  /usr/local/s-ui/sui admin -username "$SUI_ADMIN_USERNAME" -password "$SUI_ADMIN_PASSWORD"
  echo "admin_password=updated"
else
  echo "admin_password=skipped"
fi

echo
echo "== configure-panel: panel settings =="
/usr/local/s-ui/sui setting \
  -port "$WEB_PORT" \
  -path "$WEB_PATH" \
  -subPort "$SUB_PORT" \
  -subPath "$SUB_PATH"

systemctl restart s-ui.service

echo
echo "== configure-panel: current settings =="
/usr/local/s-ui/sui setting -show
"""


def run(values: dict[str, str]) -> int:
    required = ("WEB_PORT", "WEB_PATH", "SUB_PORT", "SUB_PATH")
    for key in required:
        if not values.get(key):
            print(f"ERROR: {key} 为空，无法配置面板")
            return 1

    command = (
        "sudo env "
        f"SUI_ADMIN_USERNAME={_shell_quote(values.get('SUI_INITIAL_ADMIN_USERNAME', ''))} "
        f"SUI_ADMIN_PASSWORD={_shell_quote(values.get('SUI_INITIAL_ADMIN_PASSWORD', ''))} "
        f"WEB_PORT={_shell_quote(values['WEB_PORT'])} "
        f"WEB_PATH={_shell_quote(values['WEB_PATH'])} "
        f"SUB_PORT={_shell_quote(values['SUB_PORT'])} "
        f"SUB_PATH={_shell_quote(values['SUB_PATH'])} "
        f"bash -s <<'SUI_CONFIGURE_PANEL'\n{CONFIGURE_PANEL_SCRIPT}\nSUI_CONFIGURE_PANEL"
    )
    result = run_ssh(values, command, timeout=120)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
