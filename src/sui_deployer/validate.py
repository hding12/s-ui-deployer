"""Configuration validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_KEYS = (
    "VPS_HOST",
    "SSH_USER",
    "SSH_KEY_PATH",
    "DOMAIN",
)

PLACEHOLDER_VALUES = (
    "replace-me",
    "panel.example.com",
    "residential-proxy.example.com",
    "/path/to/key.pem",
    "/replace-with-random-panel-path/",
    "/replace-with-random-sub-path/",
)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_site_config(config_path: str | Path, values: dict[str, str]) -> ValidationResult:
    result = ValidationResult()
    path = Path(config_path)

    if "source" in path.parts:
        result.errors.append("真实站点配置不能放在 source/ 下，请放到 work/sites/<site-id>/site.env")

    for key in REQUIRED_KEYS:
        if not values.get(key):
            result.errors.append(f"缺少必填字段: {key}")

    for key, value in values.items():
        if value in PLACEHOLDER_VALUES:
            result.errors.append(f"{key} 仍是示例占位值: {value}")

    _validate_ports(values, result)
    _validate_outbound(values, result)
    _validate_web_paths(values, result)
    _validate_tls_bindings(values, result)
    _validate_ssh_key(values, result)

    return result


def ensure_ssh_key_permissions(values: dict[str, str]) -> str | None:
    """Set SSH private key permissions to 600 when the key exists locally."""

    ssh_key = values.get("SSH_KEY_PATH")
    if not ssh_key or ssh_key.startswith("../../"):
        return None

    key_path = Path(ssh_key).expanduser()
    if not key_path.exists():
        return None

    mode = key_path.stat().st_mode & 0o777
    if mode & 0o077:
        key_path.chmod(0o600)
        return f"SSH_KEY_PATH 权限已自动修正为 600: {ssh_key}"
    return None


def _validate_ports(values: dict[str, str], result: ValidationResult) -> None:
    for key, value in values.items():
        if not key.endswith("_PORT") and key not in {"WEB_PORT", "SUB_PORT", "SSH_PORT"}:
            continue
        if not value:
            continue
        try:
            port = int(value)
        except ValueError:
            result.errors.append(f"{key} 不是合法端口: {value}")
            continue
        if port < 1 or port > 65535:
            result.errors.append(f"{key} 超出端口范围 1-65535: {value}")


def _validate_web_paths(values: dict[str, str], result: ValidationResult) -> None:
    for key in ("WEB_PATH", "SUB_PATH"):
        value = values.get(key, "")
        if not value:
            result.warnings.append(f"{key} 为空，后续自动化需要生成长随机路径")
            continue
        if not value.startswith("/") or not value.endswith("/"):
            result.errors.append(f"{key} 必须是 /xxx/ 格式: {value}")
        if len(value.strip("/")) < 12:
            result.warnings.append(f"{key} 建议使用更长的随机路径")


def _validate_outbound(values: dict[str, str], result: ValidationResult) -> None:
    mode = _outbound_mode(values)
    if mode not in {"direct", "socks"}:
        result.errors.append(f"OUTBOUND_MODE 只能是 direct、socks 或留空: {values.get('OUTBOUND_MODE')}")
        return

    if mode == "direct":
        return

    if values.get("OUTBOUND_TYPE", "socks") != "socks":
        result.errors.append(f"OUTBOUND_TYPE 当前只支持 socks: {values.get('OUTBOUND_TYPE')}")
    if not values.get("OUTBOUND_SERVER"):
        result.errors.append("OUTBOUND_MODE=socks 时缺少必填字段: OUTBOUND_SERVER")
    if not values.get("OUTBOUND_PORT"):
        result.errors.append("OUTBOUND_MODE=socks 时缺少必填字段: OUTBOUND_PORT")


def _outbound_mode(values: dict[str, str]) -> str:
    mode = values.get("OUTBOUND_MODE", "").strip().lower()
    if mode:
        return mode
    if values.get("OUTBOUND_SERVER") and values.get("OUTBOUND_PORT"):
        return "socks"
    return "direct"


def _validate_tls_bindings(values: dict[str, str], result: ValidationResult) -> None:
    expected = {
        "INBOUND_VLESS_TLS_TAG": "TLS_REALITY_TAG",
        "INBOUND_TUIC_TLS_TAG": "TLS_STANDARD_TAG",
        "INBOUND_HYSTERIA2_TLS_TAG": "TLS_HYSTERIA2_TAG",
        "INBOUND_TROJAN_TLS_TAG": "TLS_STANDARD_TAG",
    }
    for inbound_key, tls_key in expected.items():
        inbound_value = values.get(inbound_key)
        tls_value = values.get(tls_key)
        if inbound_value and tls_value and inbound_value != tls_value:
            result.errors.append(f"{inbound_key}={inbound_value} 与 {tls_key}={tls_value} 不一致")


def _validate_ssh_key(values: dict[str, str], result: ValidationResult) -> None:
    ssh_key = values.get("SSH_KEY_PATH")
    if not ssh_key or ssh_key.startswith("../../"):
        return
    key_path = Path(ssh_key).expanduser()
    if not key_path.exists():
        result.warnings.append(f"SSH_KEY_PATH 当前不存在: {ssh_key}")
        return
    mode = key_path.stat().st_mode & 0o777
    if mode & 0o077:
        result.errors.append(f"SSH_KEY_PATH 权限过宽，建议 chmod 600: {ssh_key}")
