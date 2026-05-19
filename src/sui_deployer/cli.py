"""Command-line entrypoint for S-UI deployment workflows."""

from __future__ import annotations

import argparse

from sui_deployer.config import ConfigError, load_env
from sui_deployer.validate import ensure_ssh_key_permissions, validate_site_config
from sui_deployer.workflow import (
    api_export,
    api_token,
    apply as apply_workflow,
    backup,
    bootstrap,
    cert,
    chain,
    configure_https,
    configure_panel,
    diagnose,
)


COMMANDS = (
    "check",
    "diagnose",
    "bootstrap",
    "configure-panel",
    "configure-https",
    "create-api-token",
    "issue-cert",
    "backup",
    "api-export",
    "plan-apply",
    "apply",
    "chain-import-current",
    "chain-list",
    "chain-show",
    "chain-plan-create",
    "chain-apply-create",
    "chain-plan-delete",
    "chain-apply-delete",
    # Phase 6: Certificate auto-renewal
    "cert-status",
    "cert-renew",
    "cert-supervise",
    "install-cert-supervisor",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sui-deploy")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("config", help="Path to work/sites/<site-id>/site.env")
    parser.add_argument("extra_args", nargs="*", help="Extra arguments (chain-id, chain.json path)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        values = load_env(args.config)
    except ConfigError as exc:
        print(f"配置解析失败: {exc}")
        return 1

    try:
        permission_message = ensure_ssh_key_permissions(values)
    except OSError as exc:
        print(f"ERROR: SSH 私钥权限自动修正失败: {exc}")
        return 1
    if permission_message:
        print(f"INFO: {permission_message}")

    if args.command == "check":
        result = validate_site_config(args.config, values)
        for warning in result.warnings:
            print(f"WARN: {warning}")
        for error in result.errors:
            print(f"ERROR: {error}")
        if not result.ok:
            return 1
        print(f"OK: 配置校验通过: {args.config}")
        return 0

    if args.command == "diagnose":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return diagnose.run(values)

    if args.command == "bootstrap":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return bootstrap.run(values)

    if args.command == "configure-panel":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return configure_panel.run(values)

    if args.command == "issue-cert":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return cert.run(values)

    if args.command == "configure-https":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return configure_https.run(values)

    if args.command == "create-api-token":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return api_token.run(values, args.config)

    if args.command == "api-export":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return api_export.run(values, args.config)

    if args.command == "backup":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return backup.run(values, args.config)

    if args.command == "plan-apply":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return apply_workflow.plan(values, args.config)

    if args.command == "apply":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return apply_workflow.apply(values, args.config)

    # ── Chain commands ──

    if args.command == "chain-import-current":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return chain.cmd_import_current(values, args.config)

    if args.command == "chain-list":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return chain.cmd_list(values, args.config)

    if args.command == "chain-show":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        chain_id = args.extra_args[0] if args.extra_args else ""
        if not chain_id:
            print("ERROR: chain-show requires a chain-id argument")
            print("  Usage: sui-deploy chain-show <site.env> <chain-id>")
            return 1
        return chain.cmd_show(values, args.config, chain_id)

    if args.command == "chain-plan-create":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        chain_path = args.extra_args[0] if args.extra_args else ""
        if not chain_path:
            print("ERROR: chain-plan-create requires a chain.json file path")
            print("  Usage: sui-deploy chain-plan-create <site.env> <chain.json>")
            return 1
        return chain.cmd_plan_create(values, args.config, chain_path)

    if args.command == "chain-apply-create":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        chain_path = args.extra_args[0] if args.extra_args else ""
        if not chain_path:
            print("ERROR: chain-apply-create requires a chain.json file path")
            print("  Usage: sui-deploy chain-apply-create <site.env> <chain.json>")
            return 1
        return chain.cmd_apply_create(values, args.config, chain_path)

    if args.command == "chain-plan-delete":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        chain_id = args.extra_args[0] if args.extra_args else ""
        if not chain_id:
            print("ERROR: chain-plan-delete requires a chain-id argument")
            print("  Usage: sui-deploy chain-plan-delete <site.env> <chain-id>")
            return 1
        return chain.cmd_plan_delete(values, args.config, chain_id)

    if args.command == "chain-apply-delete":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        chain_id = args.extra_args[0] if args.extra_args else ""
        if not chain_id:
            print("ERROR: chain-apply-delete requires a chain-id argument")
            print("  Usage: sui-deploy chain-apply-delete <site.env> <chain-id>")
            return 1
        return chain.cmd_apply_delete(values, args.config, chain_id)

    # ── Phase 6: Certificate commands ──

    if args.command == "cert-status":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return cert.cmd_status(values, args.config)

    if args.command == "cert-renew":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        dry_run = "--dry-run" in args.extra_args
        force = "--force" in args.extra_args
        return cert.cmd_renew(values, args.config, dry_run=dry_run, force=force)

    if args.command == "cert-supervise":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return cert.cmd_supervise(values, args.config)

    if args.command == "install-cert-supervisor":
        result = validate_site_config(args.config, values)
        if result.errors:
            for error in result.errors:
                print(f"ERROR: {error}")
            return 1
        return cert.cmd_install_supervisor(values, args.config)

    print(f"{args.command}: not implemented yet; config={args.config}")
    return 2
