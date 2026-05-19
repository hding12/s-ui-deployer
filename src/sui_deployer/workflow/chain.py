"""Chain-level workflow: import, list, show, plan/apply create, plan/apply delete.

Each chain = one user + one inbound + one outbound strategy + one route binding.

Route binding uses per-inbound route rules, NOT global route.final change.
This ensures multiple chains with different outbounds can coexist safely.

These commands do NOT modify apply.py or the site-level plan-apply/apply logic.
"""

from __future__ import annotations

import copy
import json
import secrets
import string
import time
import uuid
from pathlib import Path
from typing import Any

from sui_deployer.chain import (
    delete_chain_file,
    list_chain_ids,
    load_chain,
    make_chain_id_from_name,
    save_chain,
    validate_chain_dict,
)
from sui_deployer.sui_api import SuiApiError, SuiApiV2, web_base_url
from sui_deployer.workflow.backup import BackupError, create_remote_backup


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


# ── Public command entry points ──


def cmd_import_current(values: dict[str, str], config_path: str) -> int:
    """Import the current primary client + its first inbound as a chain."""
    try:
        api = _build_api(values)
        load = _api_load(api)
    except Exception as exc:
        print(f"ERROR: 无法加载面板状态: {exc}")
        return 1

    clients = load.get("clients") or []
    inbounds = load.get("inbounds") or []
    outbounds = load.get("outbounds") or []
    config = load.get("config") or {}

    client_name = values.get("SITE_ID") or values.get("CLIENT_NAME") or "primary-client"
    client = _find_by_name(clients, client_name)
    if not client:
        print(f"ERROR: 未找到名称为 {client_name!r} 的主客户端")
        return 1

    # Determine outbound mode from route rules first, then fall back to route.final
    client_inbound_ids: list[int] = client.get("inbounds") or []
    if not client_inbound_ids:
        site_inbound = inbounds[0] if inbounds else {}
    else:
        first_id = client_inbound_ids[0]
        site_inbound = next(
            (ib for ib in inbounds if ib.get("id") == first_id), {}
        )

    inbound_tag = site_inbound.get("tag", "")
    route_rules = ((config.get("route") or {}).get("rules") or [])
    matching_rule = _find_route_rule(route_rules, inbound_tag)

    if matching_rule:
        rule_outbound_tag = matching_rule.get("outbound", "")
        outbound_tag = rule_outbound_tag
        matched_outbound = _find_by_tag(outbounds, rule_outbound_tag)
        if matched_outbound:
            outbound_data = matched_outbound
            outbound_mode = "shared"  # import can't determine ownership
        else:
            outbound_data = {}
            outbound_mode = "shared"
    else:
        route_final = (config.get("route") or {}).get("final", "direct")
        outbound_mode, outbound_tag, outbound_data = _detect_outbound_from_load(
            route_final, outbounds
        )

    chain_id = make_chain_id_from_name(client_name)
    chain_data = {
        "chain_id": chain_id,
        "name": client_name,
        "client": {
            "uuid": _client_uuid(client),
            "password": _client_password(client),
            "volume": client.get("volume", 0),
            "expiry": client.get("expiry", 0),
        },
        "inbound": {
            "type": site_inbound.get("type", "vless"),
            "tag": site_inbound.get("tag", ""),
            "listen_port": site_inbound.get("listen_port", 0),
            "tls_tag": _resolve_tls_tag(site_inbound, load),
            "transport": site_inbound.get("transport", {}),
            "addrs": site_inbound.get("addrs", []),
        },
        "outbound": {
            "mode": outbound_mode,
            "tag": outbound_tag,
            "type": "socks",
            "server": outbound_data.get("server", ""),
            "server_port": outbound_data.get("server_port", 0),
            "username": outbound_data.get("username", ""),
            "password": outbound_data.get("password", ""),
        },
        "metadata": {
            "imported_from": "chain-import-current",
            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "client_id": client.get("id"),
            "inbound_id": site_inbound.get("id"),
        },
    }

    path = save_chain(config_path, chain_id, chain_data)
    print(f"OK: 已从当前站点导入主链路")
    print(f"  Chain ID: {chain_id}")
    print(f"  Client: {client_name}")
    print(f"  Inbound: {site_inbound.get('tag', '?')} ({site_inbound.get('type', '?')})")
    print(f"  Outbound mode: {outbound_mode}")
    print(f"  已保存到: {path}")
    print(f"  HINT: 运行 chain-list 查看所有链路, chain-show <chain-id> 查看详情")
    return 0


def cmd_list(values: dict[str, str], config_path: str) -> int:
    """List all chains for this site."""
    ids = list_chain_ids(config_path)
    if not ids:
        print("当前站点没有已注册的链路。")
        print("HINT: 运行 chain-import-current 导入现有主链路后重试")
        return 0

    print(f"共 {len(ids)} 条链路:")
    print(f"  {'Chain ID':<30} {'Name':<20} {'Inbound':<20} {'Outbound'}")
    print(f"  {'-'*28:<30} {'-'*18:<20} {'-'*18:<20} {'-'*18}")
    for cid in ids:
        try:
            data = load_chain(config_path, cid)
        except FileNotFoundError:
            continue
        name = data.get("name", "?")
        inbound_type = (data.get("inbound") or {}).get("type", "?")
        outbound_mode = (data.get("outbound") or {}).get("mode", "?")
        print(f"  {cid:<30} {name:<20} {inbound_type:<20} {outbound_mode}")
    return 0


def cmd_show(values: dict[str, str], config_path: str, chain_id: str) -> int:
    """Show details of a single chain (redacted)."""
    try:
        data = load_chain(config_path, chain_id)
    except FileNotFoundError:
        print(f"ERROR: 未找到链路: {chain_id}")
        print(f"  HINT: 运行 chain-list 查看所有可用链路的 Chain ID")
        return 1

    redacted = _redact_chain(data)
    print(json.dumps(redacted, ensure_ascii=False, indent=2))
    return 0


def cmd_plan_create(values: dict[str, str], config_path: str, chain_path: str) -> int:
    """Generate a plan for creating a chain without modifying remote."""
    try:
        chain_data = _read_chain_file(chain_path)
    except Exception as exc:
        print(f"ERROR: 读取链路文件失败: {exc}")
        return 1

    errors = validate_chain_dict(chain_data)
    if errors:
        print("ERROR: 链路配置校验失败:")
        for err in errors:
            print(f"  - {err}")
        return 1

    try:
        api = _build_api(values)
        load = _api_load(api)
    except Exception as exc:
        print(f"ERROR: 无法加载面板状态: {exc}")
        return 1

    errors, warnings = _check_create_conflicts(chain_data, load)
    if errors:
        print("ERROR: 前置校验未通过:")
        for err in errors:
            print(f"  - {err}")
        return 1
    for warn in warnings:
        print(f"WARN: {warn}")

    _print_create_plan(chain_data)

    print(f"OK: 创建计划已生成（未修改远端）")
    return 0


def cmd_apply_create(values: dict[str, str], config_path: str, chain_path: str) -> int:
    """Apply a chain create: backup → create outbound/inbound/client/route → restart → verify."""
    # ── 0. Load and validate ──
    try:
        chain_data = _read_chain_file(chain_path)
    except Exception as exc:
        print(f"ERROR: 读取链路文件失败: {exc}")
        return 1

    errors = validate_chain_dict(chain_data)
    if errors:
        print("ERROR: 链路配置校验失败:")
        for err in errors:
            print(f"  - {err}")
        return 1

    try:
        api = _build_api(values)
        load = _api_load(api)
    except Exception as exc:
        print(f"ERROR: 无法加载面板状态: {exc}")
        return 1

    # ── 1. Pre-flight check (stop before backup if fatal errors) ──
    errors, warnings = _check_create_conflicts(chain_data, load)
    if errors:
        print("ERROR: 前置校验未通过，已停止:")
        for err in errors:
            print(f"  - {err}")
        return 1
    for warn in warnings:
        print(f"WARN: {warn}")

    # ── 2. Backup ──
    try:
        backup_path = create_remote_backup(values, config_path)
    except BackupError as exc:
        print(f"ERROR: apply 前置备份失败，已停止: {exc}")
        return 1
    print(f"OK: 前置备份完成: {backup_path}")

    # ── 3. Create outbound (dedicated mode only) ──
    outbound = chain_data.get("outbound", {})
    outbound_mode = outbound.get("mode", "direct")
    inbound_tag = chain_data.get("inbound", {}).get("tag", "")

    if outbound_mode == "dedicated":
        outbound_payload = _build_outbound_payload(chain_data)
        existing_outbound = _find_by_tag(
            load.get("outbounds") or [], outbound_payload["tag"]
        )
        action = "edit" if existing_outbound else "new"
        if existing_outbound:
            outbound_payload["id"] = existing_outbound["id"]
        try:
            _api_save(api, "outbounds", action, outbound_payload)
            print(f"  OK: 出站 {action} -> {outbound_payload['tag']}")
        except SuiApiError as exc:
            print(f"ERROR: 创建出站失败: {exc}")
            return 1

    # ── 4. Create inbound ──
    tls_tag = chain_data.get("inbound", {}).get("tls_tag", "")
    tls_id = _find_tls_id(load, tls_tag)
    if tls_id is None:
        print(f"ERROR: 未找到 TLS 模板 '{tls_tag}'，请先在面板中创建")
        return 1

    inbound_payload = _build_inbound_payload(chain_data, tls_id)
    existing_inbound = _find_by_tag(
        load.get("inbounds") or [], inbound_payload["tag"]
    )
    inbound_action = "edit" if existing_inbound else "new"
    if existing_inbound:
        inbound_payload["id"] = existing_inbound["id"]

    try:
        save_response = _api_save(api, "inbounds", inbound_action, inbound_payload)
        print(f"  OK: 入站 {inbound_action} -> {inbound_payload['tag']}")
    except SuiApiError as exc:
        print(f"ERROR: 创建入站失败: {exc}")
        return 1

    inbound_id = _extract_new_id(
        save_response, "inbounds", "tag", inbound_payload["tag"]
    )

    # ── 5. Create/update client ──
    inbound_type = chain_data.get("inbound", {}).get("type", "vless")
    client_payload = _build_client_payload(chain_data, inbound_type, inbound_id)

    existing_client = _find_by_name(
        load.get("clients") or [], client_payload["name"]
    )
    client_action = "edit" if existing_client else "new"
    if existing_client:
        client_payload["id"] = existing_client["id"]
        existing_inbound_ids: list[int] = existing_client.get("inbounds") or []
        if inbound_id and inbound_id not in existing_inbound_ids:
            existing_inbound_ids.append(inbound_id)
        client_payload["inbounds"] = existing_inbound_ids

    try:
        _api_save(api, "clients", client_action, client_payload)
        print(f"  OK: 客户端 {client_action} -> {client_payload['name']}")
    except SuiApiError as exc:
        print(f"ERROR: 创建客户端失败: {exc}")
        return 1

    # ── 6. Add route rule: inbound_tag → outbound_tag ──
    if outbound_mode in ("dedicated", "shared"):
        outbound_tag = outbound.get("tag", "")
        if outbound_tag:
            _add_route_rule(api, load, inbound_tag, outbound_tag)
        # Reload to get fresh config for next operations
        load = _api_load(api)

    # ── 7. Restart core ──
    _api_restart_core(api)

    # ── 8. Save chain file with generated credentials ──
    _update_chain_data_with_generated(chain_data, client_payload)
    chain_data.setdefault("metadata", {})["inbound_id"] = inbound_id or 0
    chain_id = chain_data.get("chain_id", make_chain_id_from_name(chain_data.get("name", "chain")))
    save_chain(config_path, chain_id, chain_data)
    print(f"OK: 链路已保存到 chains/{chain_id}.json")

    # ── 9. Verify (returns bool, affects exit code) ──
    try:
        final_load = _api_load(api)
        all_ok = _verify_chain_created(chain_data, final_load)
    except Exception as exc:
        print(f"ERROR: 验证失败: {exc}")
        return 1

    if not all_ok:
        print(f"WARN: 链路 '{chain_data.get('name', '')}' 创建完成，但验证发现部分对象未就绪")
        print(f"  HINT: 运行 chain-show {chain_id} 检查链路状态")
        return 1

    print(f"OK: 链路 '{chain_data.get('name', '')}' 创建完成")
    print(f"  HINT: 运行 chain-list 确认, chain-show {chain_id} 查看详情")
    print(f"  HINT: 在面板中检查入站、客户端和订阅链接")
    return 0


def cmd_plan_delete(values: dict[str, str], config_path: str, chain_id: str) -> int:
    """Generate a plan for deleting a chain without modifying remote."""
    try:
        chain_data = load_chain(config_path, chain_id)
    except FileNotFoundError:
        print(f"ERROR: 未找到链路: {chain_id}")
        print(f"  HINT: 运行 chain-list 查看所有可用链路的 Chain ID")
        return 1

    try:
        api = _build_api(values)
        load = _api_load(api)
    except Exception as exc:
        print(f"ERROR: 无法加载面板状态: {exc}")
        return 1

    print(f"删除计划 — 链路: {chain_id} ({chain_data.get('name', '?')})")
    print(f"  {_format_delete_plan(chain_data, load, config_path)}")
    print()
    print(f"OK: 删除计划已生成（未修改远端）")
    print(f"  HINT: 确认无误后运行 chain-apply-delete {chain_id}")
    return 0


def cmd_apply_delete(values: dict[str, str], config_path: str, chain_id: str) -> int:
    """Apply a chain delete: backup → clean route/outbound/client/inbound → restart → verify."""
    try:
        chain_data = load_chain(config_path, chain_id)
    except FileNotFoundError:
        print(f"ERROR: 未找到链路: {chain_id}")
        print(f"  HINT: 运行 chain-list 查看所有可用链路的 Chain ID")
        return 1

    try:
        api = _build_api(values)
        load = _api_load(api)
    except Exception as exc:
        print(f"ERROR: 无法加载面板状态: {exc}")
        return 1

    # ── 1. Backup ──
    try:
        backup_path = create_remote_backup(values, config_path)
    except BackupError as exc:
        print(f"ERROR: apply 前置备份失败，已停止: {exc}")
        return 1
    print(f"OK: 前置备份完成: {backup_path}")

    inbound_tag = chain_data.get("inbound", {}).get("tag", "")

    # ── 2. Remove route rule for this inbound ──
    _remove_route_rule(api, load, inbound_tag)
    load = _api_load(api)

    # ── 3. Detach inbound from client, then delete inbound ──
    client_name = chain_data.get("name", "")
    clients = load.get("clients") or []
    client = _find_by_name(clients, client_name)
    chain_inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)
    chain_inbound_id = chain_inbound.get("id") if chain_inbound else None

    if client and chain_inbound_id:
        client_id = client.get("id")
        remaining = [ib_id for ib_id in (client.get("inbounds") or []) if ib_id is not None]
        remaining = [ib_id for ib_id in remaining if ib_id != chain_inbound_id]

        if not remaining:
            # No more inbounds — delete the client entirely
            try:
                _api_save(api, "clients", "del", {"id": client_id})
                print(f"  OK: 客户端已删除 -> {client_name}")
            except SuiApiError as exc:
                print(f"WARN: 删除客户端失败: {exc}")
                return 1
        else:
            # Client has other inbounds — write back updated list
            try:
                _write_client_inbounds(api, load, client, remaining)
                print(f"  OK: 客户端 '{client_name}' 入站列表已裁剪（剩余 {len(remaining)} 个）")
            except SuiApiError as exc:
                print(f"WARN: 更新客户端入站列表失败: {exc}")
                print(f"  WARN: 入站 ID 在客户端中可能仍为悬空引用")
    elif client:
        # Client exists but inbound not found in load — might be already deleted
        print(f"  INFO: 客户端 '{client_name}' 存在，但入站 '{inbound_tag}' 未找到，跳过裁剪")

    # ── 4. Delete inbound ──
    if inbound_tag:
        inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)
        if inbound:
            try:
                _api_save(api, "inbounds", "del", {"id": inbound["id"]})
                print(f"  OK: 入站已删除 -> {inbound_tag}")
            except SuiApiError as exc:
                print(f"WARN: 删除入站失败: {exc}")
        else:
            print(f"  INFO: 入站 '{inbound_tag}' 不存在，跳过")

    # ── 5. Delete outbound (dedicated mode only, with ownership check) ──
    outbound = chain_data.get("outbound", {})
    if outbound.get("mode") == "dedicated":
        outbound_tag = outbound.get("tag", "")
        if outbound_tag:
            if _outbound_has_other_references(config_path, outbound_tag, exclude_chain_id=chain_id):
                print(f"  WARN: 出站 '{outbound_tag}' 仍被其他链路引用，跳过删除")
            else:
                existing = _find_by_tag(load.get("outbounds") or [], outbound_tag)
                if existing:
                    try:
                        _api_save(api, "outbounds", "del", {"id": existing["id"]})
                        print(f"  OK: 专属出站已删除 -> {outbound_tag}")
                    except SuiApiError as exc:
                        print(f"WARN: 删除出站失败: {exc}")

    # ── 6. Restart core ──
    _api_restart_core(api)

    # ── 7. Remove chain file ──
    if delete_chain_file(config_path, chain_id):
        print(f"  OK: 本地链路文件已删除: chains/{chain_id}.json")
    else:
        print(f"  WARN: 未找到本地链路文件: chains/{chain_id}.json")

    # ── 8. Verify (returns bool, affects exit code) ──
    try:
        final_load = _api_load(api)
        all_ok = _verify_chain_deleted(chain_data, final_load, config_path, chain_inbound_id)
    except Exception:
        all_ok = False

    if not all_ok:
        print(f"WARN: 链路 '{chain_id}' 删除完成，但验证发现部分对象仍未清除")
        print(f"  HINT: 运行 diagnose 检查远端状态")
        return 1

    print(f"OK: 链路 '{chain_id}' 删除完成")
    return 0


# ── Internal API helpers ──


def _build_api(values: dict[str, str]) -> SuiApiV2:
    token = values.get("SUI_API_TOKEN", "")
    if not token:
        raise SuiApiError("SUI_API_TOKEN 为空，请先运行 create-api-token")
    verify_tls = values.get("SUI_API_TLS_VERIFY", "true").lower() == "true"
    return SuiApiV2(
        web_base_url(values, scheme="https", host=values["DOMAIN"]),
        token=token,
        resolve_ip=values.get("VPS_HOST"),
        verify_tls=verify_tls,
    )


def _api_load(api: SuiApiV2) -> dict[str, Any]:
    response = api.get("apiv2/load")
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/load 返回失败: {response.get('msg')}")
    return response.get("obj") or {}


def _api_save(
    api: SuiApiV2,
    obj: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    data = {
        "object": obj,
        "action": action,
        "data": json.dumps(payload, ensure_ascii=False),
    }
    # initUsers is only set for clients action
    if obj == "clients" and action in ("new", "edit"):
        init_users = payload.pop("_init_users", None)
        if init_users is not None:
            data["initUsers"] = ",".join(str(uid) for uid in init_users)
    response = api.post("apiv2/save", data)
    if not response.get("success"):
        raise SuiApiError(f"/apiv2/save {obj}/{action} 失败: {response.get('msg')}")
    print(f"    API: {obj}/{action} 成功")
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


# ── Route rule management ──

# Route rules use per-inbound matching, NOT global route.final.
# Format: {"inbound": ["inbound-tag"], "outbound": "outbound-tag"}


def _add_route_rule(
    api: SuiApiV2,
    load: dict[str, Any],
    inbound_tag: str,
    outbound_tag: str,
) -> None:
    """Add a route rule: inbound_tag → outbound_tag. Idempotent."""
    config = copy.deepcopy(load.get("config") or {})
    config.setdefault("route", {})

    rules: list[dict[str, Any]] = config["route"].get("rules") or []

    # Remove existing rule for same inbound (idempotent)
    rules = [r for r in rules if r.get("inbound") != [inbound_tag]]

    # Add new rule
    rules.append({"inbound": [inbound_tag], "outbound": outbound_tag})
    config["route"]["rules"] = rules

    # Preserve route.final — don't touch it
    if "final" not in config["route"]:
        config["route"]["final"] = "direct"

    try:
        _api_save(api, "config", "edit", config)
        print(f"  OK: 新增路由规则: inbound={inbound_tag} -> outbound={outbound_tag}")
    except SuiApiError as exc:
        print(f"WARN: 新增路由规则失败: {exc}")


def _remove_route_rule(
    api: SuiApiV2,
    load: dict[str, Any],
    inbound_tag: str,
) -> None:
    """Remove all route rules matching the given inbound tag."""
    config = copy.deepcopy(load.get("config") or {})
    config.setdefault("route", {})
    rules: list[dict[str, Any]] = config["route"].get("rules") or []

    before = len(rules)
    rules = [r for r in rules if r.get("inbound") != [inbound_tag]]
    after = len(rules)

    if before == after:
        print(f"  INFO: 未找到入站 '{inbound_tag}' 的路由规则，跳过")
        return

    config["route"]["rules"] = rules

    try:
        _api_save(api, "config", "edit", config)
        print(f"  OK: 已移除入站 '{inbound_tag}' 的路由规则")
    except SuiApiError as exc:
        print(f"WARN: 移除路由规则失败: {exc}")


# ── Client inbounds management ──


def _write_client_inbounds(
    api: SuiApiV2,
    load: dict[str, Any],
    client: dict[str, Any],
    inbounds: list[int],
) -> None:
    """Write back updated inbounds list for an existing client. Raises on failure."""
    payload = copy.deepcopy(client)
    payload["inbounds"] = inbounds
    payload.pop("config", None)  # Don't overwrite config on edit
    _api_save(api, "clients", "edit", payload)


# ── Ownership checks ──


def _outbound_has_other_references(config_path: str, outbound_tag: str, exclude_chain_id: str = "") -> bool:
    """Check if any chain file OTHER than exclude_chain_id references this outbound tag."""
    ids = list_chain_ids(config_path)
    for cid in ids:
        if cid == exclude_chain_id:
            continue
        try:
            data = load_chain(config_path, cid)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        outbound = data.get("outbound") or {}
        if outbound.get("tag") == outbound_tag and outbound.get("mode") in ("shared", "dedicated"):
            return True
    return False


# ── Payload builders ──


def _build_outbound_payload(chain_data: dict[str, Any]) -> dict[str, Any]:
    outbound = chain_data.get("outbound", {})
    return {
        "id": 0,
        "type": outbound.get("type", "socks"),
        "tag": outbound.get("tag", ""),
        "server": outbound.get("server", ""),
        "server_port": int(outbound.get("server_port", 0)),
        "version": "5",
        "username": outbound.get("username", ""),
        "password": outbound.get("password", ""),
    }


def _build_inbound_payload(
    chain_data: dict[str, Any], tls_id: int
) -> dict[str, Any]:
    inbound = chain_data.get("inbound", {})
    payload: dict[str, Any] = {
        "id": 0,
        "type": inbound.get("type", "vless"),
        "tag": inbound.get("tag", ""),
        "listen": "::",
        "listen_port": int(inbound.get("listen_port", 0)),
        "tls_id": tls_id,
        "transport": inbound.get("transport", {}),
        "addrs": inbound.get("addrs", []),
        "out_json": {},
    }
    return payload


def _build_client_payload(
    chain_data: dict[str, Any],
    inbound_type: str,
    inbound_id: int | None,
) -> dict[str, Any]:
    """Build a client payload. Returns it with _init_users for the caller to strip.

    Generated UUIDs/passwords are stored in the returned payload['config'];
    the caller is responsible for saving them back to chain_data (see
    _update_chain_data_with_generated).
    """
    name = chain_data.get("name", "")
    client = chain_data.get("client", {})

    if inbound_type == "vless":
        config = {
            "vless": {
                "name": name,
                "uuid": client.get("uuid") or str(uuid.uuid4()),
                "flow": "xtls-rprx-vision",
            }
        }
    elif inbound_type == "tuic":
        config = {
            "tuic": {
                "name": name,
                "uuid": client.get("uuid") or str(uuid.uuid4()),
                "password": client.get("password") or _random_password(20),
            }
        }
    elif inbound_type == "hysteria2":
        config = {
            "hysteria2": {
                "name": name,
                "password": client.get("password") or _random_password(20),
            }
        }
    elif inbound_type == "trojan":
        config = {
            "trojan": {
                "name": name,
                "password": client.get("password") or _random_password(20),
            }
        }
    else:
        config = {
            inbound_type: {
                "name": name,
                "password": client.get("password") or _random_password(20),
            }
        }

    inbounds: list[int] = []
    if inbound_id is not None:
        inbounds.append(inbound_id)

    payload = {
        "id": 0,
        "enable": True,
        "name": name,
        "config": config,
        "inbounds": inbounds,
        "links": [],
        "volume": client.get("volume", 0),
        "expiry": client.get("expiry", 0),
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

    # Store init_users so _api_save can extract it
    if inbound_id is not None:
        payload["_init_users"] = [inbound_id]

    return payload


def _update_chain_data_with_generated(
    chain_data: dict[str, Any],
    client_payload: dict[str, Any],
) -> None:
    """Extract generated UUID/password from client payload and save back to chain_data.

    This ensures the local chain file stays in sync with the deployed state.
    """
    config = client_payload.get("config", {})
    if "vless" in config and isinstance(config["vless"], dict):
        uuid_val = config["vless"].get("uuid", "")
        if uuid_val:
            chain_data.setdefault("client", {})["uuid"] = uuid_val
    if "tuic" in config and isinstance(config["tuic"], dict):
        uuid_val = config["tuic"].get("uuid", "")
        if uuid_val:
            chain_data.setdefault("client", {})["uuid"] = uuid_val
        pw = config["tuic"].get("password", "")
        if pw:
            chain_data.setdefault("client", {})["password"] = pw
    if "hysteria2" in config and isinstance(config["hysteria2"], dict):
        pw = config["hysteria2"].get("password", "")
        if pw:
            chain_data.setdefault("client", {})["password"] = pw
    if "trojan" in config and isinstance(config["trojan"], dict):
        pw = config["trojan"].get("password", "")
        if pw:
            chain_data.setdefault("client", {})["password"] = pw

    # Generic fallback: save password from any unknown protocol type
    for proto_key, proto_config in config.items():
        if not isinstance(proto_config, dict):
            continue
        if proto_key in ("vless", "tuic", "hysteria2", "trojan"):
            continue  # already handled above
        pw = proto_config.get("password", "")
        if pw:
            chain_data.setdefault("client", {})["password"] = pw


# ── Conflict detection ──


def _check_create_conflicts(
    chain_data: dict[str, Any], load: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Check for conflicts before creating a chain.

    Returns (errors, warnings):
      errors  — fatal: stop execution (missing shared outbound, TLS, port conflict)
      warnings — informational: will auto-handle (tag already exists → edit)
    """
    errors: list[str] = []
    warnings: list[str] = []

    inbound = chain_data.get("inbound", {})
    inbound_tag = inbound.get("tag", "")
    inbound_port = inbound.get("listen_port", 0)

    existing_inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)
    if existing_inbound:
        warnings.append(f"入站 tag '{inbound_tag}' 已存在 (ID={existing_inbound.get('id')})，将转为 edit")

    for ib in load.get("inbounds") or []:
        if ib.get("listen_port") == inbound_port and ib.get("tag") != inbound_tag:
            errors.append(
                f"端口 {inbound_port} 已被入站 '{ib.get('tag')}' 占用，无法创建"
            )

    client_name = chain_data.get("name", "")
    existing_client = _find_by_name(load.get("clients") or [], client_name)
    if existing_client:
        warnings.append(f"客户端名称 '{client_name}' 已存在 (ID={existing_client.get('id')})，将合并入站")

    outbound = chain_data.get("outbound", {})
    outbound_tag = outbound.get("tag", "")
    if outbound.get("mode") == "dedicated":
        existing_outbound = _find_by_tag(load.get("outbounds") or [], outbound_tag)
        if existing_outbound:
            warnings.append(
                f"出站 tag '{outbound_tag}' 已存在 (ID={existing_outbound.get('id')})，将转为 edit"
            )

    if outbound.get("mode") == "shared":
        if not outbound_tag:
            errors.append("outbound.tag is required for mode='shared'")
        elif not _find_by_tag(load.get("outbounds") or [], outbound_tag):
            errors.append(
                f"出站 tag '{outbound_tag}' 在面板中不存在。shared 模式需要引用一个已存在的出站"
            )

    tls_tag = inbound.get("tls_tag", "")
    tls_items = load.get("tls") or []
    if not _find_by_name(tls_items, tls_tag):
        errors.append(f"TLS 模板 '{tls_tag}' 在面板中不存在，需要先创建")

    return errors, warnings


# ── Planning output ──


def _print_create_plan(chain_data: dict[str, Any]) -> None:
    """Print a human-readable create plan."""
    name = chain_data.get("name", "?")
    inbound = chain_data.get("inbound", {})
    outbound = chain_data.get("outbound", {})
    outbound_mode = outbound.get("mode", "direct")
    inbound_tag = inbound.get("tag", "")
    outbound_tag = outbound.get("tag", "")

    print(f"创建计划 — 链路: {name}")
    print(f"  客户端: {name}")
    print(f"  入站: {inbound.get('type')} on :{inbound.get('listen_port')} ({inbound_tag})")
    print(f"    TLS 模板: {inbound.get('tls_tag')}")
    print(f"  出站模式: {outbound_mode}")
    if outbound_mode == "dedicated":
        print(f"    类型: {outbound.get('type')} -> {outbound.get('server')}:{outbound.get('server_port')}")
        print(f"    Tag: {outbound.get('tag')}")
    elif outbound_mode == "shared":
        print(f"    引用现有出站: {outbound_tag}")
    if outbound_mode in ("dedicated", "shared"):
        print(f"  路由规则: {inbound_tag} -> {outbound_tag} (新增)"
              if outbound_tag and inbound_tag else "")
    print()


def _format_delete_plan(
    chain_data: dict[str, Any], load: dict[str, Any], config_path: str
) -> str:
    """Format a delete plan summary string."""
    lines: list[str] = []
    name = chain_data.get("name", "?")
    inbound_tag = chain_data.get("inbound", {}).get("tag", "")

    client = _find_by_name(load.get("clients") or [], name)
    if client:
        client_inbound_count = len(client.get("inbounds") or [])
        lines.append(f"客户端: {name} (ID={client.get('id')}, {client_inbound_count} 个入站)")
    else:
        lines.append(f"客户端: {name} (不存在)")

    inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)
    if inbound:
        lines.append(f"入站: {inbound_tag} (ID={inbound.get('id')})")
    else:
        lines.append(f"入站: {inbound_tag} (不存在)")

    outbound = chain_data.get("outbound", {})
    if outbound.get("mode") == "dedicated":
        outbound_tag = outbound.get("tag", "")
        existing = _find_by_tag(load.get("outbounds") or [], outbound_tag)
        refs = _outbound_has_other_references(config_path, outbound_tag, exclude_chain_id=chain_data.get("chain_id", ""))
        if existing:
            ref_note = " (有其他引用)" if refs else " (无其他引用)"
            lines.append(f"专属出站: {outbound_tag} (ID={existing.get('id')}){ref_note}")
        else:
            lines.append(f"专属出站: {outbound_tag} (不存在)")

    # Route rule
    rules = ((load.get("config") or {}).get("route") or {}).get("rules") or []
    has_rule = any(r.get("inbound") == [inbound_tag] for r in rules)
    lines.append(f"路由规则: {inbound_tag}{' (存在)' if has_rule else ' (不存在)'}")

    return "\n  ".join(lines)


# ── Verification (returns bool) ──


def _verify_chain_created(chain_data: dict[str, Any], load: dict[str, Any]) -> bool:
    """Verify a chain was created successfully. Returns True if all objects exist."""
    name = chain_data.get("name", "")
    inbound_tag = chain_data.get("inbound", {}).get("tag", "")
    outbound_tag = chain_data.get("outbound", {}).get("tag", "")
    outbound_mode = chain_data.get("outbound", {}).get("mode", "direct")

    client = _find_by_name(load.get("clients") or [], name)
    inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)

    all_ok = True

    print(f"  验证:")
    if client:
        print(f"    客户端 '{name}': 找到 ✓")
    else:
        print(f"    客户端 '{name}': 未找到 ✗")
        all_ok = False

    if inbound:
        print(f"    入站 '{inbound_tag}': 找到 ✓")
    else:
        print(f"    入站 '{inbound_tag}': 未找到 ✗")
        all_ok = False

    if outbound_mode in ("dedicated", "shared") and outbound_tag:
        outbound_obj = _find_by_tag(load.get("outbounds") or [], outbound_tag)
        if outbound_obj:
            print(f"    出站 '{outbound_tag}': 找到 ✓")
        else:
            print(f"    出站 '{outbound_tag}': 未找到 ✗")
            all_ok = False

    # Verify route rule
    config = load.get("config") or {}
    rules = ((config.get("route") or {}).get("rules") or [])
    if outbound_mode in ("dedicated", "shared") and inbound_tag:
        has_rule = any(
            r.get("inbound") == [inbound_tag] and r.get("outbound") == outbound_tag
            for r in rules
        )
        if has_rule:
            print(f"    路由规则 {inbound_tag} -> {outbound_tag}: 存在 ✓")
        else:
            print(f"    路由规则 {inbound_tag} -> {outbound_tag}: 未找到 ✗")
            all_ok = False

    route_final = (config.get("route") or {}).get("final", "?")
    print(f"    默认路由 final: {route_final} (未修改)")
    return all_ok


def _verify_chain_deleted(
    chain_data: dict[str, Any], load: dict[str, Any],
    config_path: str = "",
    inbound_id: int | None = None,
) -> bool:
    """Verify a chain was deleted successfully. Returns True if all objects are gone.

    inbound_id: the inbound's ID before deletion, used to detect stale client references.
    Falls back to chain_data.metadata.inbound_id if not provided.
    """
    name = chain_data.get("name", "")
    inbound_tag = chain_data.get("inbound", {}).get("tag", "")

    client = _find_by_name(load.get("clients") or [], name)
    inbound = _find_by_tag(load.get("inbounds") or [], inbound_tag)

    all_ok = True

    print(f"  验证:")
    if client:
        remaining_inbounds: list[int] = client.get("inbounds") or []

        # Check for stale reference: the deleted inbound's ID still in client list
        target_inbound_id = inbound_id or chain_data.get("metadata", {}).get("inbound_id")
        if target_inbound_id and target_inbound_id in remaining_inbounds:
            print(f"    客户端 '{name}': inbounds 列表中残留已删除入站 ID ({target_inbound_id}) ✗")
            all_ok = False
        else:
            # Also verify by tag — if inbound object still exists and is linked
            inbound_objects = load.get("inbounds") or []
            client_inbound_tags = [
                ib.get("tag") for ib in inbound_objects
                if ib.get("id") in remaining_inbounds
            ]
            if inbound_tag in client_inbound_tags:
                print(f"    客户端 '{name}': 存在但仍有指向已删除入站的引用 ✗")
                all_ok = False
            else:
                print(f"    客户端 '{name}': 保留（其他入站正常） ✓")
    else:
        print(f"    客户端 '{name}': 已删除 ✓")

    if inbound:
        print(f"    入站 '{inbound_tag}': 仍然存在 ✗")
        all_ok = False
    else:
        print(f"    入站 '{inbound_tag}': 已删除 ✓")

    outbound = chain_data.get("outbound", {})
    if outbound.get("mode") == "dedicated":
        outbound_tag = outbound.get("tag", "")
        outbound_obj = _find_by_tag(load.get("outbounds") or [], outbound_tag)
        if outbound_obj:
            # It may legitimately exist if others reference it
            chain_id = chain_data.get("chain_id", "")
            if config_path and _outbound_has_other_references(config_path, outbound_tag, exclude_chain_id=chain_id):
                print(f"    专属出站 '{outbound_tag}': 仍被其他链路引用，保留 ✓")
            else:
                print(f"    专属出站 '{outbound_tag}': 残留且无人引用，应已删除 ✗")
                all_ok = False
        else:
            print(f"    专属出站 '{outbound_tag}': 已删除 ✓")

    # Verify route rule removed
    config = load.get("config") or {}
    rules = ((config.get("route") or {}).get("rules") or [])
    has_rule = any(r.get("inbound") == [inbound_tag] for r in rules)
    if has_rule:
        print(f"    路由规则 '{inbound_tag}': 仍然存在 ✗")
        all_ok = False
    else:
        print(f"    路由规则 '{inbound_tag}': 已清除 ✓")

    return all_ok


# ── Helper functions ──


def _find_by_tag(items: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("tag") == tag), None)


def _find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("name") == name), None)


def _find_tls_id(load: dict[str, Any], tls_tag: str) -> int | None:
    tls_items = load.get("tls") or []
    tls = _find_by_name(tls_items, tls_tag)
    if tls:
        return int(tls.get("id", 0))
    return None


def _resolve_tls_tag(inbound: dict[str, Any], load: dict[str, Any]) -> str:
    tls_id = inbound.get("tls_id")
    if not tls_id:
        return ""
    tls_items = load.get("tls") or []
    for tls in tls_items:
        if int(tls.get("id", 0)) == int(tls_id):
            return tls.get("name") or ""
    return ""


def _extract_new_id(
    save_response: dict[str, Any],
    obj_key: str,
    match_key: str,
    match_value: str,
) -> int | None:
    obj_list = (save_response.get("obj") or {}).get(obj_key) or []
    for item in obj_list:
        if str(item.get(match_key, "")) == match_value:
            return int(item.get("id", 0))
    return None


def _detect_outbound_from_load(
    route_final: str, outbounds: list[dict[str, Any]]
) -> tuple[str, str, dict[str, Any]]:
    if route_final in ("direct", "", None):
        return "direct", "", {}

    outbound = _find_by_tag(outbounds, route_final)
    if outbound:
        return "shared", route_final, outbound

    return "shared", route_final, {}


def _find_route_rule(
    rules: list[dict[str, Any]], inbound_tag: str
) -> dict[str, Any] | None:
    """Find a route rule matching the given inbound tag."""
    for rule in rules:
        inbounds_list = rule.get("inbound")
        if isinstance(inbounds_list, list) and inbound_tag in inbounds_list:
            return rule
    return None


def _client_uuid(client: dict[str, Any]) -> str:
    config = client.get("config") or {}
    for key in ("vless", "tuic"):
        proto_config = config.get(key)
        if isinstance(proto_config, dict):
            uuid_val = proto_config.get("uuid", "")
            if uuid_val:
                return uuid_val
    return ""


def _client_password(client: dict[str, Any]) -> str:
    config = client.get("config") or {}
    for key in ("tuic", "hysteria2", "trojan"):
        proto_config = config.get(key)
        if isinstance(proto_config, dict):
            pw = proto_config.get("password", "")
            if pw:
                return pw
    return ""


def _read_chain_file(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"链路文件不存在: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def _random_password(length: int) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _redact_chain(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data

    redacted: dict[str, Any] = {}
    for key, value in data.items():
        lower_key = key.lower()
        if lower_key in SENSITIVE_KEYS or any(
            part in lower_key for part in ("password", "token", "secret")
        ):
            redacted[key] = "***REDACTED***" if value not in ("", None) else value
        elif isinstance(value, dict):
            redacted[key] = _redact_chain(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_chain(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
