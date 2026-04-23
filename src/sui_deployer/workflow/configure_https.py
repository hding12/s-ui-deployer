"""Configure S-UI web and subscription HTTPS through the web API."""

from __future__ import annotations

import json

from sui_deployer.sui_api import SuiApiError, SuiWebApi, web_base_url


def run(values: dict[str, str]) -> int:
    username = values.get("SUI_INITIAL_ADMIN_USERNAME", "")
    password = values.get("SUI_INITIAL_ADMIN_PASSWORD", "")
    if not username or not password:
        print("ERROR: S-UI 管理员用户名或密码为空，无法登录 API")
        return 1

    base_url = web_base_url(values, scheme="http", host=values.get("VPS_HOST"))
    verify_tls = values.get("SUI_API_TLS_VERIFY", "true").lower() == "true"
    api = SuiWebApi(base_url, resolve_ip=values.get("VPS_HOST"), verify_tls=verify_tls)
    try:
        api.login(username, password)
        settings_response = api.get("api/settings")
    except Exception as exc:
        print(f"ERROR: API 登录或读取 settings 失败: {exc}")
        return 1

    if not settings_response.get("success"):
        print(f"ERROR: 读取 settings 失败: {settings_response.get('msg')}")
        return 1

    settings = settings_response.get("obj") or {}
    settings.update(
        {
            "webDomain": values["DOMAIN"],
            "webPort": values["WEB_PORT"],
            "webPath": values["WEB_PATH"],
            "webCertFile": values["SSL_CERT_FULLCHAIN_PATH"],
            "webKeyFile": values["SSL_CERT_KEY_PATH"],
            "subDomain": values["DOMAIN"],
            "subPort": values["SUB_PORT"],
            "subPath": values["SUB_PATH"],
            "subCertFile": values["SSL_CERT_FULLCHAIN_PATH"],
            "subKeyFile": values["SSL_CERT_KEY_PATH"],
        }
    )

    save_payload = {
        "object": "settings",
        "action": "set",
        "data": json.dumps(settings, separators=(",", ":")),
    }
    try:
        save_response = api.post("api/save", save_payload)
        if not save_response.get("success"):
            print(f"ERROR: 保存 settings 失败: {save_response.get('msg')}")
            return 1
        restart_response = api.post("api/restartApp", {})
        if not restart_response.get("success"):
            print(f"ERROR: 重启 S-UI 失败: {restart_response.get('msg')}")
            return 1
    except SuiApiError as exc:
        print(f"ERROR: API 请求失败: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: HTTPS 配置请求失败: {exc}")
        return 1

    print("OK: 已通过 S-UI API 配置 Web/订阅 HTTPS")
    print(f"web_url=https://{values['DOMAIN']}:{values['WEB_PORT']}{values['WEB_PATH']}")
    print(f"sub_url=https://{values['DOMAIN']}:{values['SUB_PORT']}{values['SUB_PATH']}")
    return 0
