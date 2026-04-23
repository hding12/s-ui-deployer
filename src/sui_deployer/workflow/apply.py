"""Plan and apply workflow."""

from __future__ import annotations

import copy
import json
import secrets
import string
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sui_deployer.sui_api import SuiApiError, SuiApiV2, web_base_url
from sui_deployer.workflow.backup import BackupError, create_remote_backup


PLAN_FILE = "plan-apply.raw.json"
REDACTED_PLAN_FILE = "plan-apply.redacted.json"


SENSITIVE_KEYS = {
    "password",
    "pass",
    "token",
    "private_key",
    "public_key",
    "short_id",
    "uuid",
    "username",
    "path",
    "key_path",
    "certificate_path",
}


@dataclass
class ApiContext:
    api: SuiApiV2
    load: dict[str, Any]


def plan(values: dict[str, str], config_path: str) -> int:
    try:
        ctx = _load_context(values)
        plan_data = _build_plan(values, ctx.load, ctx.api)
    except Exception as exc:
        print(f"ERROR: 生成 plan-apply 失败: {exc}")
        return 1

    output_dir = _generated_dir(config_path)
    raw_path = output_dir / PLAN_FILE
    redacted_path = output_dir / REDACTED_PLAN_FILE
    raw_path.write_text(json.dumps(plan_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redacted_path.write_text(json.dumps(redact(plan_data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: 原始执行计划已写入 {raw_path}")
    print(f"OK: 脱敏执行计划已写入 {redacted_path}")
    _print_plan_summary(plan_data)
    return 0


def apply(values: dict[str, str], config_path: str) -> int:
    try:
        ctx = _load_context(values)
        plan_data = _read_or_build_plan(values, config_path, ctx.load, ctx.api)
    except Exception as exc:
        print(f"ERROR: 读取或生成执行计划失败: {exc}")
        return 1

    if not plan_data.get("operations"):
        print("OK: 没有需要应用的变更")
        return 0

    try:
        backup_path = create_remote_backup(values, config_path)
    except BackupError as exc:
        print(f"ERROR: apply 前置备份失败，已停止: {exc}")
        return 1
    print(f"OK: apply 前置备份已完成: {backup_path}")

    try:
        _apply_operations(ctx.api, plan_data["operations"])
        final_load = _api_load(ctx.api)
    except Exception as exc:
        print(f"ERROR: apply 失败，远端已保留备份用于回滚: {backup_path}")
        print(f"ERROR: {exc}")
        return 1

    output_dir = _generated_dir(config_path)
    result_path = output_dir / f"apply-result-{time.strftime('%Y%m%d-%H%M%S')}.json"
    result_path.write_text(json.dumps(redact(final_load), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: apply 完成，脱敏结果已写入 {result_path}")
    print("下一步验证：重新运行 diagnose 和 api-export，然后在浏览器打开面板检查 TLS、出站、客户端、入站。")
    return 0


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lower_key = key.lower()
            if lower_key in SENSITIVE_KEYS or any(part in lower_key for part in ("password", "token", "secret")):
                redacted[key] = "***REDACTED***" if item not in ("", None) else item
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _load_context(values: dict[str, str]) -> ApiContext:
    token = values.get("SUI_API_TOKEN", "")
    if not token:
        raise SuiApiError("SUI_API_TOKEN 为空，请先运行 create-api-token")
    verify_tls = values.get("SUI_API_TLS_VERIFY", "true").lower() == "true"
    api = SuiApiV2(
        web_base_url(values, scheme="https", host=values["DOMAIN"]),
        token=token,
        resolve_ip=values.get("VPS_HOST"),
        verify_tls=verify_tls,
    )
    return ApiContext(api=api, load=_api_load(api))


def _api_load(api: SuiApiV2) -> dict[str, Any]:
    response = api.get("apiv2/load")
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/load 返回失败: {response.get('msg')}")
    return response.get("obj") or {}


def _build_plan(values: dict[str, str], load: dict[str, Any], api: SuiApiV2 | None = None) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    tls_items = load.get("tls") or []
    outbounds = load.get("outbounds") or []
    clients = load.get("clients") or []
    inbounds = load.get("inbounds") or []
    config = copy.deepcopy(load.get("config") or {})

    tls_payloads = [
        _tls_reality(values, _reality_keypair(values, api)),
        _tls_standard(values),
        _tls_hysteria2(values),
    ]
    for payload in tls_payloads:
        existing = _find_by_name(tls_items, payload["name"])
        payload["id"] = existing.get("id", 0) if existing else 0
        operations.append(_save_operation("tls", "edit" if existing else "new", payload))

    config.setdefault("route", {})
    outbound_mode = outbound_mode_from_config(values)
    if outbound_mode == "socks":
        outbound_payload = _outbound_socks(values)
        existing_outbound = _find_by_tag(outbounds, outbound_payload["tag"])
        outbound_payload["id"] = existing_outbound.get("id", 0) if existing_outbound else 0
        operations.append(_save_operation("outbounds", "edit" if existing_outbound else "new", outbound_payload))
        config["route"]["final"] = outbound_payload["tag"]
    else:
        config["route"]["final"] = "direct"
    operations.append(_save_operation("config", "edit", config))

    tls_ids = _planned_tls_ids(tls_items, tls_payloads)
    inbound_payloads = [
        _inbound_vless(values, tls_ids[values.get("TLS_REALITY_TAG", "reality")]),
        _inbound_tuic(values, tls_ids[values.get("TLS_STANDARD_TAG", "tls")]),
        _inbound_hysteria2(values, tls_ids[values.get("TLS_HYSTERIA2_TAG", "hy2-tls")]),
        _inbound_trojan(values, tls_ids[values.get("TLS_STANDARD_TAG", "tls")]),
    ]
    inbound_ids = _planned_inbound_ids(inbounds, inbound_payloads)
    for payload in inbound_payloads:
        existing_inbound = _find_by_tag(inbounds, payload["tag"])
        payload["id"] = existing_inbound.get("id", 0) if existing_inbound else 0
        operation = _save_operation("inbounds", "edit" if existing_inbound else "new", payload)
        operations.append(operation)

    client_name = _client_name(values)
    existing_client = _find_by_name(clients, client_name)
    legacy_client_name = values.get("CLIENT_NAME", "")
    if not existing_client and legacy_client_name and legacy_client_name != client_name:
        existing_client = _find_by_name(clients, legacy_client_name)
    existing_client = _full_client(existing_client, api)
    client_payload = _client(values, existing_client)
    client_payload["id"] = existing_client.get("id", 0) if existing_client else 0
    client_payload["inbounds"] = [inbound_ids[payload["tag"]] for payload in inbound_payloads]
    operations.append(_save_operation("clients", "edit" if existing_client else "new", client_payload))

    return {
        "site_id": values.get("SITE_ID", ""),
        "domain": values.get("DOMAIN", ""),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": [
            "plan-apply 不修改远端配置。",
            "apply 会先备份 /usr/local/s-ui/db/s-ui.db 和证书目录，再调用 /apiv2/save。",
            "新建对象的 id 在真实 apply 时由 S-UI 生成；计划中的 id=0 表示待新建。",
        ],
        "operations": operations,
    }


def _read_or_build_plan(values: dict[str, str], config_path: str, load: dict[str, Any], api: SuiApiV2) -> dict[str, Any]:
    plan_path = _generated_dir(config_path) / PLAN_FILE
    if plan_path.exists():
        return json.loads(plan_path.read_text(encoding="utf-8"))
    return _build_plan(values, load, api)


def _apply_operations(api: SuiApiV2, operations: list[dict[str, Any]]) -> None:
    id_maps: dict[str, dict[str, int]] = {"tls": {}, "clients": {}}

    for operation in operations:
        obj = operation["object"]
        payload = copy.deepcopy(operation["data"])

        if obj == "inbounds":
            tls_name = operation.get("tls_name")
            if tls_name:
                payload["tls_id"] = id_maps["tls"].get(tls_name, payload.get("tls_id", 0))
            init_users = operation.get("initUsers") or []
            operation = {**operation, "initUsers": [id_maps["clients"].get(str(item), item) for item in init_users]}

        response = _api_save(api, obj, operation["action"], payload, operation.get("initUsers"))
        load = response.get("obj") or {}

        if obj == "tls":
            for item in load.get("tls") or []:
                if item.get("name"):
                    id_maps["tls"][item["name"]] = int(item.get("id", 0))
        elif obj == "clients":
            for item in load.get("clients") or []:
                if item.get("name"):
                    id_maps["clients"][item["name"]] = int(item.get("id", 0))

    _api_restart_core(api)


def _api_save(api: SuiApiV2, obj: str, action: str, payload: dict[str, Any], init_users: list[Any] | None = None) -> dict[str, Any]:
    data = {
        "object": obj,
        "action": action,
        "data": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    if init_users:
        data["initUsers"] = ",".join(str(item) for item in init_users)
    response = api.post("apiv2/save", data)
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/save {obj}/{action} 失败: {response.get('msg')}")
    print(f"OK: 已应用 {obj}/{action}: {_operation_label(payload)}")
    return response


def _api_restart_core(api: SuiApiV2) -> None:
    for path in ("api/restartSb", "apiv2/restartSb"):
        try:
            response = api.post(path, {})
        except Exception:
            continue
        if response.get("success"):
            print("OK: 已请求重启 S-UI core")
            return
    print("WARN: 未能通过 API 重启 core，请在面板中确认 core 状态")


def _full_client(client: dict[str, Any] | None, api: SuiApiV2 | None) -> dict[str, Any] | None:
    if not client or client.get("config") or api is None:
        return client

    client_id = client.get("id")
    if not client_id:
        return client
    response = api.get(f"apiv2/clients?id={client_id}")
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/clients?id={client_id} 返回失败: {response.get('msg')}")
    clients = (response.get("obj") or {}).get("clients") or []
    full_client = next((item for item in clients if item.get("id") == client_id), None)
    return full_client or client


def _save_operation(obj: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    operation = {"object": obj, "action": action, "data": payload}
    if obj == "inbounds":
        operation["tls_name"] = payload.pop("_tls_name")
    if obj == "clients":
        operation["client_name"] = payload.get("name")
    return operation


def _reality_keypair(values: dict[str, str], api: SuiApiV2 | None) -> tuple[str, str]:
    private_key = values.get("TLS_REALITY_PRIVATE_KEY", "")
    public_key = values.get("TLS_REALITY_PUBLIC_KEY", "")
    if private_key and public_key:
        return private_key, public_key
    if api is None:
        return private_key or _random_token(43), public_key

    response = api.get("apiv2/keypairs?k=reality")
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/keypairs?k=reality 返回失败: {response.get('msg')}")
    obj = response.get("obj")
    if not isinstance(obj, list) or len(obj) < 2:
        raise SuiApiError("/apiv2/keypairs?k=reality 响应格式不符合预期")
    parsed_private = _keypair_value(str(obj[0]), "PrivateKey")
    parsed_public = _keypair_value(str(obj[1]), "PublicKey")
    return private_key or parsed_private, public_key or parsed_public


def _keypair_value(value: str, label: str) -> str:
    if ":" not in value:
        return value.strip()
    key, raw = value.split(":", 1)
    if key.strip() != label:
        raise SuiApiError(f"/apiv2/keypairs?k=reality 返回字段顺序异常: {key.strip()}")
    return raw.strip()


def _tls_reality(values: dict[str, str], keypair: tuple[str, str]) -> dict[str, Any]:
    private_key, public_key = keypair
    short_id = values.get("TLS_REALITY_SHORT_ID") or ""
    server = values.get("TLS_REALITY_HANDSHAKE_SERVER", "aws.amazon.com")
    port = int(values.get("TLS_REALITY_HANDSHAKE_PORT", "443"))
    return {
        "id": 0,
        "name": values.get("TLS_REALITY_TAG", "reality"),
        "server": {
            "enabled": True,
            "server_name": server,
            "reality": {
                "enabled": True,
                "handshake": {"server": server, "server_port": port},
                "private_key": private_key,
                "short_id": [short_id] if short_id else [],
            },
        },
        "client": {
            "enabled": True,
            "server_name": server,
            "utls": {"enabled": True, "fingerprint": values.get("TLS_REALITY_UTLS_FINGERPRINT", "chrome")},
            "reality": {"enabled": True, "public_key": public_key, "short_id": short_id},
        },
    }


def _tls_standard(values: dict[str, str]) -> dict[str, Any]:
    alpn = _csv(values.get("TLS_STANDARD_ALPN", "h3,h2,http/1.1"))
    return {
        "id": 0,
        "name": values.get("TLS_STANDARD_TAG", "tls"),
        "server": {
            "enabled": True,
            "server_name": values.get("TLS_STANDARD_SERVER_NAME") or values["DOMAIN"],
            "certificate_path": values["SSL_CERT_FULLCHAIN_PATH"],
            "key_path": values["SSL_CERT_KEY_PATH"],
            "alpn": alpn,
        },
        "client": {
            "enabled": True,
            "server_name": values.get("TLS_STANDARD_SERVER_NAME") or values["DOMAIN"],
            "insecure": values.get("TLS_STANDARD_ALLOW_INSECURE", "true").lower() == "true",
            "alpn": alpn,
        },
    }


def _tls_hysteria2(values: dict[str, str]) -> dict[str, Any]:
    alpn = _csv(values.get("TLS_HYSTERIA2_ALPN", "h3"))
    return {
        "id": 0,
        "name": values.get("TLS_HYSTERIA2_TAG", "hy2-tls"),
        "server": {
            "enabled": True,
            "server_name": values.get("TLS_HYSTERIA2_SERVER_NAME") or values["DOMAIN"],
            "certificate_path": values["SSL_CERT_FULLCHAIN_PATH"],
            "key_path": values["SSL_CERT_KEY_PATH"],
            "alpn": alpn,
        },
        "client": {
            "enabled": True,
            "server_name": values.get("TLS_HYSTERIA2_SERVER_NAME") or values["DOMAIN"],
            "insecure": values.get("TLS_HYSTERIA2_ALLOW_INSECURE", "true").lower() == "true",
            "alpn": alpn,
        },
    }


def _outbound_socks(values: dict[str, str]) -> dict[str, Any]:
    return {
        "id": 0,
        "type": "socks",
        "tag": values.get("OUTBOUND_TAG", "socks-residential"),
        "server": values["OUTBOUND_SERVER"],
        "server_port": int(values["OUTBOUND_PORT"]),
        "version": "5",
        "username": values.get("OUTBOUND_USERNAME", ""),
        "password": values.get("OUTBOUND_PASSWORD", ""),
    }


def outbound_mode_from_config(values: dict[str, str]) -> str:
    mode = values.get("OUTBOUND_MODE", "").strip().lower()
    if mode:
        return mode
    if values.get("OUTBOUND_SERVER") and values.get("OUTBOUND_PORT"):
        return "socks"
    return "direct"


def _client(values: dict[str, str], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    name = _client_name(values)
    if existing:
        payload = copy.deepcopy(existing)
        payload.setdefault("config", {})
        payload.setdefault("links", [])
        _rename_client_payload(payload, name)
        return payload

    tuic_uuid = str(uuid.uuid4())
    vless_uuid = str(uuid.uuid4())
    password = _random_password(20)
    return {
        "id": 0,
        "enable": True,
        "name": name,
        "config": {
            "vless": {"name": name, "uuid": vless_uuid, "flow": "xtls-rprx-vision"},
            "tuic": {"name": name, "uuid": tuic_uuid, "password": _random_password(20)},
            "hysteria2": {"name": name, "password": password},
            "trojan": {"name": name, "password": _random_password(20)},
        },
        "inbounds": [],
        "links": [],
        "volume": 0,
        "expiry": 0,
        "up": 0,
        "down": 0,
        "desc": "",
        "group": "",
        "delayStart": False,
        "autoReset": False,
        "resetDays": 0,
        "nextReset": 0,
        "totalUp": 0,
        "totalDown": 0,
    }


def _client_name(values: dict[str, str]) -> str:
    return values.get("SITE_ID") or values.get("CLIENT_NAME") or "primary-client"


def _rename_client_payload(payload: dict[str, Any], name: str) -> None:
    payload["name"] = name
    config = payload.get("config")
    if not isinstance(config, dict):
        return
    for protocol_config in config.values():
        if not isinstance(protocol_config, dict):
            continue
        if any(key in protocol_config for key in ("uuid", "password", "flow", "auth_str")) and "username" not in protocol_config:
            protocol_config["name"] = name
        if "name" in protocol_config:
            protocol_config["name"] = name
        if "username" in protocol_config:
            protocol_config["username"] = name


def _inbound_vless(values: dict[str, str], tls_id: int) -> dict[str, Any]:
    return {
        "id": 0,
        "type": "vless",
        "tag": values.get("INBOUND_VLESS_TAG", "vless-reality"),
        "listen": "::",
        "listen_port": int(values.get("INBOUND_VLESS_PORT", "443")),
        "tls_id": tls_id,
        "transport": {},
        "addrs": [{"server": values["DOMAIN"], "server_port": int(values.get("INBOUND_VLESS_PORT", "443"))}],
        "out_json": {},
        "_tls_name": values.get("TLS_REALITY_TAG", "reality"),
    }


def _inbound_tuic(values: dict[str, str], tls_id: int) -> dict[str, Any]:
    return {
        "id": 0,
        "type": "tuic",
        "tag": values.get("INBOUND_TUIC_TAG", "tuic-59501"),
        "listen": "::",
        "listen_port": int(values.get("INBOUND_TUIC_PORT", "59501")),
        "congestion_control": "bbr",
        "tls_id": tls_id,
        "addrs": [{"server": values["DOMAIN"], "server_port": int(values.get("INBOUND_TUIC_PORT", "59501"))}],
        "out_json": {},
        "_tls_name": values.get("TLS_STANDARD_TAG", "tls"),
    }


def _inbound_hysteria2(values: dict[str, str], tls_id: int) -> dict[str, Any]:
    port = int(values.get("HYSTERIA2_UDP_PORT") or values.get("INBOUND_HYSTERIA2_PORT", "8443"))
    return {
        "id": 0,
        "type": "hysteria2",
        "tag": values.get("INBOUND_HYSTERIA2_TAG", "hysteria2"),
        "listen": "::",
        "listen_port": port,
        "tls_id": tls_id,
        "addrs": [{"server": values["DOMAIN"], "server_port": port}],
        "out_json": {},
        "_tls_name": values.get("TLS_HYSTERIA2_TAG", "hy2-tls"),
    }


def _inbound_trojan(values: dict[str, str], tls_id: int) -> dict[str, Any]:
    port = int(values.get("INBOUND_TROJAN_PORT", "41101"))
    return {
        "id": 0,
        "type": "trojan",
        "tag": values.get("INBOUND_TROJAN_TAG", "trojan-ws"),
        "listen": "::",
        "listen_port": port,
        "tls_id": tls_id,
        "transport": {
            "type": "ws",
            "path": values.get("INBOUND_TROJAN_WS_PATH") or f"/ws-{_random_token(18)}",
            "headers": {"Host": values.get("INBOUND_TROJAN_HOST", "aws.amazon.com")},
        },
        "addrs": [{"server": values["DOMAIN"], "server_port": port}],
        "out_json": {},
        "_tls_name": values.get("TLS_STANDARD_TAG", "tls"),
    }


def _planned_tls_ids(existing: list[dict[str, Any]], planned: list[dict[str, Any]]) -> dict[str, int]:
    next_id = max([int(item.get("id", 0)) for item in existing] or [0]) + 1
    ids: dict[str, int] = {}
    for payload in planned:
        current = _find_by_name(existing, payload["name"])
        if current:
            ids[payload["name"]] = int(current["id"])
        else:
            ids[payload["name"]] = next_id
            next_id += 1
    return ids


def _planned_inbound_ids(existing: list[dict[str, Any]], planned: list[dict[str, Any]]) -> dict[str, int]:
    next_id = max([int(item.get("id", 0)) for item in existing] or [0]) + 1
    ids: dict[str, int] = {}
    for payload in planned:
        current = _find_by_tag(existing, payload["tag"])
        if current:
            ids[payload["tag"]] = int(current["id"])
        else:
            ids[payload["tag"]] = next_id
            next_id += 1
    return ids


def _find_by_tag(items: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("tag") == tag), None)


def _find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("name") == name), None)


def _generated_dir(config_path: str) -> Path:
    output_dir = Path(config_path).parent / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _random_password(length: int) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _random_token(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _operation_label(payload: dict[str, Any]) -> str:
    return str(payload.get("tag") or payload.get("name") or payload.get("id") or "-")


def _print_plan_summary(plan_data: dict[str, Any]) -> None:
    print("计划摘要:")
    for index, operation in enumerate(plan_data.get("operations", []), start=1):
        payload = operation.get("data", {})
        print(f"  {index}. {operation['object']}/{operation['action']} -> {_operation_label(payload)}")
