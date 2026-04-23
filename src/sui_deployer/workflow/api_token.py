"""Create and persist an S-UI API token."""

from __future__ import annotations

import json
from pathlib import Path

from sui_deployer.sui_api import SuiWebApi, web_base_url


def run(values: dict[str, str], config_path: str) -> int:
    username = values.get("SUI_INITIAL_ADMIN_USERNAME", "")
    password = values.get("SUI_INITIAL_ADMIN_PASSWORD", "")
    if not username or not password:
        print("ERROR: S-UI 管理员用户名或密码为空，无法创建 API token")
        return 1

    if values.get("SUI_API_TOKEN"):
        print("OK: SUI_API_TOKEN 已存在，跳过创建")
        return 0

    base_url = web_base_url(values, scheme="https", host=values["DOMAIN"])
    verify_tls = values.get("SUI_API_TLS_VERIFY", "true").lower() == "true"
    api = SuiWebApi(base_url, resolve_ip=values.get("VPS_HOST"), verify_tls=verify_tls)
    try:
        api.login(username, password)
        response = api.post(
            "api/addToken",
            {
                "desc": f"automation-{values.get('SITE_ID', 'site')}",
                "expiry": "0",
            },
        )
    except Exception as exc:
        print(f"ERROR: 创建 API token 失败: {exc}")
        return 1

    if not response.get("success"):
        print(f"ERROR: 创建 API token 失败: {response.get('msg')}")
        return 1

    token = _find_token(response.get("obj"))
    if not token:
        print("ERROR: API token 已创建但响应中未找到 token 值")
        print(json.dumps(response, ensure_ascii=False))
        return 1

    _replace_env_value(Path(config_path), "SUI_API_TOKEN", token)
    _replace_env_value(Path(config_path), "SUI_API_TOKEN_SOURCE", "api/addToken")
    print("OK: API token 已创建并写入 site.env")
    print("token=***REDACTED***")
    return 0


def _find_token(obj: object) -> str | None:
    if isinstance(obj, str) and len(obj) >= 16:
        return obj
    if isinstance(obj, dict):
        for key in ("token", "api_token", "apiToken", "key"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                return value
        for value in obj.values():
            found = _find_token(value)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_token(item)
            if found:
                return found
    return None


def _replace_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    replacement = f'{key}="{value}"'
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
