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
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sui-deploy")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("config", help="Path to work/sites/<site-id>/site.env")
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

    print(f"{args.command}: not implemented yet; config={args.config}")
    return 2
