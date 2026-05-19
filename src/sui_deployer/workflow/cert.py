"""Certificate issuance and auto-renewal workflows.

Phase 3 — issue-cert: run()
Phase 6 — Certificate auto-renewal closed loop:
  - cmd_status()              — read-only observation
  - cmd_renew()               — single manual renew cycle
  - cmd_supervise()           — state machine supervision
  - cmd_install_supervisor()  — deploy remote systemd timer
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sui_deployer.ssh import SSHResult, run_ssh


# ── Phase 3: issue-cert (existing) ────────────────────────────────────────

ISSUE_CERT_SCRIPT = r"""
set -euo pipefail

domain="${DOMAIN}"
port="${SSL_HTTP_PORT:-80}"
cert_dir="/root/cert/${domain}"
fullchain="${cert_dir}/fullchain.pem"
privkey="${cert_dir}/privkey.pem"

echo "== issue-cert: precheck =="
echo "domain=${domain}"
echo "http_port=${port}"
if [ -f "$fullchain" ] && [ -f "$privkey" ]; then
  echo "cert_status=exists"
  openssl x509 -in "$fullchain" -noout -subject -issuer -dates || true
  exit 0
fi

echo
echo "== issue-cert: s-ui ssl menu =="
printf '19\n1\n%s\n%s\n' "$domain" "$port" | s-ui

echo
echo "== issue-cert: verify =="
test -f "$fullchain"
test -f "$privkey"
chmod 755 "$fullchain" "$privkey"
openssl x509 -in "$fullchain" -noout -subject -issuer -dates
echo "fullchain=${fullchain}"
echo "privkey=${privkey}"
"""


def run(values: dict[str, str]) -> int:
    """Issue certificate via S-UI menu (Phase 3)."""
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空，无法申请证书")
        return 1

    port = values.get("SSL_HTTP_PORT", "80")
    command = (
        "sudo env -u SUDO_USER -u SUDO_UID -u SUDO_GID -u SUDO_COMMAND "
        f"HOME=/root DOMAIN={_shell_quote(domain)} SSL_HTTP_PORT={_shell_quote(port)} "
        f"bash -s <<'SUI_ISSUE_CERT'\n{ISSUE_CERT_SCRIPT}\nSUI_ISSUE_CERT"
    )
    result = run_ssh(values, command, timeout=900)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


# ── Phase 6: Certificate auto-renewal ─────────────────────────────────────

# ── Constants ──────────────────────────────────────────────────────────────

SUPERVISOR_DIR = "/usr/local/s-ui-deployer"
STATE_DIR = "/var/lib/s-ui-deployer"
LOG_DIR = "/var/log/s-ui-deployer"
STATE_FILE = f"{STATE_DIR}/cert-state.json"

SENSITIVE_CERT_KEYS = {
    "password",
    "token",
    "private_key",
    "key_path",
    "certificate_path",
    "uuid",
}


# ── Data model ─────────────────────────────────────────────────────────────


@dataclass
class CertState:
    """Certificate state as observed on the remote VPS."""

    domain: str = ""
    cert_path: str = ""
    key_path: str = ""
    not_before: str = ""
    not_after: str = ""
    lifetime_days: int = 0
    days_remaining: float = 0.0
    renew_before_days: int = 30
    urgent_before_days: int = 15
    state: str = "unknown"
    service_active: bool = False
    dns_matches_expected: bool = False
    file_fingerprint_sha256: str = ""
    served_fingerprints: dict[str, str] = field(default_factory=dict)
    last_check_at: str = ""
    last_renew_attempt_at: str = ""
    last_renew_success_at: str = ""
    consecutive_failures: int = 0
    last_error_code: str = ""
    last_error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "cert_path": self.cert_path,
            "key_path": self.key_path,
            "not_before": self.not_before,
            "not_after": self.not_after,
            "lifetime_days": self.lifetime_days,
            "days_remaining": self.days_remaining,
            "renew_before_days": self.renew_before_days,
            "urgent_before_days": self.urgent_before_days,
            "state": self.state,
            "service_active": self.service_active,
            "dns_matches_expected": self.dns_matches_expected,
            "file_fingerprint_sha256": self.file_fingerprint_sha256,
            "served_fingerprints": self.served_fingerprints,
            "last_check_at": self.last_check_at,
            "last_renew_attempt_at": self.last_renew_attempt_at,
            "last_renew_success_at": self.last_renew_success_at,
            "consecutive_failures": self.consecutive_failures,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CertState:
        return cls(
            domain=data.get("domain", ""),
            cert_path=data.get("cert_path", ""),
            key_path=data.get("key_path", ""),
            not_before=data.get("not_before", ""),
            not_after=data.get("not_after", ""),
            lifetime_days=data.get("lifetime_days", 0),
            days_remaining=data.get("days_remaining", 0.0),
            renew_before_days=data.get("renew_before_days", 30),
            urgent_before_days=data.get("urgent_before_days", 15),
            state=data.get("state", "unknown"),
            service_active=data.get("service_active", False),
            dns_matches_expected=data.get("dns_matches_expected", False),
            file_fingerprint_sha256=data.get("file_fingerprint_sha256", ""),
            served_fingerprints=data.get("served_fingerprints", {}),
            last_check_at=data.get("last_check_at", ""),
            last_renew_attempt_at=data.get("last_renew_attempt_at", ""),
            last_renew_success_at=data.get("last_renew_success_at", ""),
            consecutive_failures=data.get("consecutive_failures", 0),
            last_error_code=data.get("last_error_code", ""),
            last_error_message=data.get("last_error_message", ""),
        )


# ── cert-status ────────────────────────────────────────────────────────────

CERT_PROBE_SCRIPT = r"""
set -u

domain="${DOMAIN}"
cert_path="/root/cert/${domain}/fullchain.pem"
key_path="/root/cert/${domain}/privkey.pem"
state_file="${CERT_STATE_DIR}/cert-state.json"

echo "== cert-status =="

# 1. Try to read existing state file
if [ -f "$state_file" ]; then
  echo "state_file_found=true"
else
  echo "state_file_found=false"
fi

# 2. Certificate files
if [ -f "$cert_path" ] && [ -f "$key_path" ]; then
  echo "cert_files=present"
  openssl x509 -in "$cert_path" -noout -subject -issuer -dates -fingerprint -sha256 2>/dev/null || echo "cert_parse_error=true"

  fp_file=$(openssl x509 -in "$cert_path" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
  echo "file_fingerprint_sha256=${fp_file}"
else
  echo "cert_files=missing"
fi

# 3. Service status
service_state=$(systemctl is-active s-ui.service 2>/dev/null || echo "unknown")
echo "service_active=${service_state}"

# 4. DNS check
if command -v getent >/dev/null 2>&1; then
  resolved=$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u | head -1)
elif command -v python3 >/dev/null 2>&1; then
  resolved=$(python3 -c "import socket; print(socket.getaddrinfo('${domain}', 80, socket.AF_INET)[0][4][0])" 2>/dev/null)
else
  resolved=$(nslookup "$domain" 2>/dev/null | awk '/^Address: /{print $2}' | head -1)
fi
echo "dns_resolved=${resolved:-unknown}"
echo "expected_ip=${EXPECTED_IP:-}"

# 5. External TLS handshake — per-port labeled output
for probe_port in ${WEB_PORT} ${SUB_PORT} ${EXTRA_VERIFY_PORTS}; do
  [ -z "$probe_port" ] && continue
  served_fp=$(echo "Q" | openssl s_client -connect "${domain}:${probe_port}" -servername "$domain" 2>/dev/null | \
    openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
  echo "tls_fp_${probe_port}=${served_fp:-missing}"
done
"""


def cmd_status(values: dict[str, str], config_path: str) -> int:
    """Read-only: observe certificate status on remote VPS.

    Returns:
        0 — status readable, not in failure state
        1 — status unreadable or probe failed
        2 — status readable, but degraded/urgent/manual_intervention
    """
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空")
        return 1

    web_port = values.get("WEB_PORT", "2095")
    sub_port = values.get("SUB_PORT", "2096")
    extra_ports = values.get("CERT_VERIFY_EXTRA_PORTS", "").strip()

    command = _sudo_cmd(
        f"DOMAIN={_shell_quote(domain)} "
        f"EXPECTED_IP={_shell_quote(values.get('VPS_HOST', ''))} "
        f"WEB_PORT={_shell_quote(web_port)} "
        f"SUB_PORT={_shell_quote(sub_port)} "
        f"EXTRA_VERIFY_PORTS={_shell_quote(extra_ports)} "
        f"CERT_STATE_DIR={STATE_DIR} "
        f"bash -s <<'CERT_STATUS'\n{CERT_PROBE_SCRIPT}\nCERT_STATUS"
    )
    result = run_ssh(values, command, timeout=60)
    if result.returncode != 0:
        print(f"ERROR: SSH 探测失败 (exit={result.returncode})")
        if result.stderr:
            print(result.stderr.rstrip())
        return 1

    # Parse probe output
    lines = result.stdout.splitlines() if result.stdout else []
    parsed = _parse_probe_output(lines)

    # Try to also read existing state file
    state = _try_read_state_file(values, domain)
    if state is None:
        state = _build_state_from_probe(parsed, domain)
    else:
        _overlay_probe_onto_state(state, parsed)

    # Compute dynamic renew thresholds
    _compute_renew_thresholds(state, values)
    _determine_state(state, values)

    # Write local copy (redacted)
    _write_local_status(config_path, state)

    # Print human-readable summary
    _print_status_summary(state)

    # Return exit code based on state
    if state.state in ("degraded", "urgent", "manual_intervention"):
        return 2
    return 0


# ── Internal helpers ──────────────────────────────────────────────────────


def _parse_probe_output(lines: list[str]) -> dict[str, Any]:
    """Parse KEY=VALUE pairs from SSH probe script output."""
    parsed: dict[str, Any] = {}
    tls_fps: dict[str, str] = {}

    for line in lines:
        line = line.strip()
        if line.startswith("== ") or line.startswith("subject="):
            continue

        # Port-labeled TLS fingerprints: tls_fp_2095=sha256:...
        if line.startswith("tls_fp_"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                port_key = parts[0].replace("tls_fp_", "")
                fp_value = parts[1].strip()
                if fp_value and fp_value != "missing":
                    tls_fps[port_key] = fp_value
            continue

        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            parsed[key] = value

    if tls_fps:
        parsed["served_fingerprints"] = tls_fps

    # Parse openssl x509 structured output from the raw text
    raw = "\n".join(lines)
    for match in _SUBJECT_RE.finditer(raw):
        parsed["subject"] = match.group(1)
    for match in _ISSUER_RE.finditer(raw):
        parsed["issuer"] = match.group(1)
    for match in _NOT_BEFORE_RE.finditer(raw):
        parsed["not_before"] = match.group(1)
    for match in _NOT_AFTER_RE.finditer(raw):
        parsed["not_after"] = match.group(1)
    for match in _FINGERPRINT_RE.finditer(raw):
        parsed["file_fingerprint_raw"] = match.group(1)

    return parsed


_SUBJECT_RE = re.compile(r"subject=\s*(.+)")
_ISSUER_RE = re.compile(r"issuer=\s*(.+)")
_NOT_BEFORE_RE = re.compile(r"notBefore=(.+)")
_NOT_AFTER_RE = re.compile(r"notAfter=(.+)")
_FINGERPRINT_RE = re.compile(r"sha256\s+ Fingerprint=(.+)", re.IGNORECASE)


def _try_read_state_file(values: dict[str, str], domain: str) -> CertState | None:
    """Try to read the remote cert-state.json via SSH."""
    command = _sudo_cmd(f"cat {STATE_FILE} 2>/dev/null || true")
    result = run_ssh(values, command, timeout=15)
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        data = json.loads(result.stdout)
        return CertState.from_dict(data)
    except (json.JSONDecodeError, ValueError):
        return None


def _build_state_from_probe(parsed: dict[str, Any], domain: str) -> CertState:
    """Construct a CertState from raw probe output."""
    now = datetime.now(timezone.utc)
    state = CertState(domain=domain, last_check_at=_iso_now())

    # Parse dates
    not_before_str = parsed.get("not_before", "")
    not_after_str = parsed.get("not_after", "")
    not_before = _parse_openssl_date(not_before_str)
    not_after = _parse_openssl_date(not_after_str)

    if not_before and not_after:
        state.not_before = not_before.isoformat()
        state.not_after = not_after.isoformat()
        lifetime = (not_after - not_before).days
        state.lifetime_days = max(lifetime, 1)
        remaining = (not_after - now).total_seconds() / 86400.0
        state.days_remaining = max(0.0, remaining)

    state.cert_path = f"/root/cert/{domain}/fullchain.pem"
    state.key_path = f"/root/cert/{domain}/privkey.pem"

    cert_files = parsed.get("cert_files", "missing")
    if cert_files == "present":
        state.file_fingerprint_sha256 = (
            parsed.get("file_fingerprint_sha256", "")
            or parsed.get("file_fingerprint_raw", "")
        )
    else:
        state.file_fingerprint_sha256 = ""

    state.service_active = parsed.get("service_active", "").lower() == "active"

    dns_resolved = parsed.get("dns_resolved", "")
    expected_ip = parsed.get("expected_ip", "")
    state.dns_matches_expected = bool(dns_resolved and expected_ip and dns_resolved == expected_ip)

    served = parsed.get("served_fingerprints")
    if isinstance(served, dict):
        state.served_fingerprints = served

    return state


def _overlay_probe_onto_state(state: CertState, parsed: dict[str, Any]) -> None:
    """Update an existing CertState with fresh probe data."""
    state.last_check_at = _iso_now()

    # Always refresh date fields from live probe data
    not_before_str = parsed.get("not_before", "")
    not_after_str = parsed.get("not_after", "")
    not_before = _parse_openssl_date(not_before_str)
    not_after = _parse_openssl_date(not_after_str)
    if not_before and not_after:
        state.not_before = not_before.isoformat()
        state.not_after = not_after.isoformat()
        lifetime = (not_after - not_before).days
        state.lifetime_days = max(lifetime, 1)

    cert_files = parsed.get("cert_files", "missing")
    if cert_files == "present":
        fp = parsed.get("file_fingerprint_sha256", "") or parsed.get("file_fingerprint_raw", "")
        if fp:
            state.file_fingerprint_sha256 = fp
    else:
        state.file_fingerprint_sha256 = ""

    state.service_active = parsed.get("service_active", "").lower() == "active"

    dns_resolved = parsed.get("dns_resolved", "")
    expected_ip = parsed.get("expected_ip", "")
    state.dns_matches_expected = bool(dns_resolved and expected_ip and dns_resolved == expected_ip)

    served = parsed.get("served_fingerprints")
    if isinstance(served, dict):
        state.served_fingerprints = served

    # Recompute remaining days with current time and fresh probe data
    now = datetime.now(timezone.utc)
    if not_after:
        remaining = (not_after - now).total_seconds() / 86400.0
        state.days_remaining = max(0.0, remaining)


def _compute_renew_thresholds(state: CertState, values: dict[str, str]) -> None:
    """Compute dynamic renew thresholds.

    Default: renew at 1/3 lifetime, urgent at 1/6 lifetime.
    Override via CERT_RENEW_BEFORE_DAYS / CERT_RENEW_URGENT_BEFORE_DAYS.
    """
    lifetime = state.lifetime_days
    if lifetime <= 0:
        lifetime = 90  # fallback

    override_renew = values.get("CERT_RENEW_BEFORE_DAYS", "").strip()
    override_urgent = values.get("CERT_RENEW_URGENT_BEFORE_DAYS", "").strip()

    if override_renew and override_renew.isdigit():
        state.renew_before_days = int(override_renew)
    else:
        state.renew_before_days = max(1, math.ceil(lifetime / 3))

    if override_urgent and override_urgent.isdigit():
        state.urgent_before_days = int(override_urgent)
    else:
        state.urgent_before_days = max(1, math.ceil(lifetime / 6))


def _expected_verify_ports(values: dict[str, str]) -> list[str]:
    """Return the list of ports that must have consistent TLS fingerprints."""
    ports = [values.get("WEB_PORT", "2095"), values.get("SUB_PORT", "2096")]
    extra = values.get("CERT_VERIFY_EXTRA_PORTS", "")
    if extra:
        ports.extend([p.strip() for p in extra.split(",") if p.strip()])
    return ports


def _probe_is_healthy(state: CertState, values: dict[str, str]) -> tuple[bool, str]:
    """Check observed certificate state against health criteria.

    Returns (True, "") if healthy, or (False, error_code) with details.
    """
    if not state.service_active:
        return False, "SERVICE_INACTIVE"
    if not state.dns_matches_expected:
        return False, "DNS_MISMATCH"
    if not state.file_fingerprint_sha256:
        return False, "CERT_FILE_MISSING"

    for port in _expected_verify_ports(values):
        served_fp = state.served_fingerprints.get(port, "")
        if not served_fp:
            return False, f"TLS_MISSING_{port}"
        if served_fp != state.file_fingerprint_sha256:
            return False, f"TLS_MISMATCH_{port}"
    return True, ""


def _determine_state(state: CertState, values: dict[str, str] | None = None) -> None:
    """Determine the control-loop state based on observations.

    Reads CERT_MAX_CONSECUTIVE_FAILURES from values when available.
    Incorporates probe health (service, DNS, TLS fingerprints) into
    state classification — a bad probe prevents a healthy verdict
    even when the certificate has plenty of days remaining.
    """
    max_failures = 5
    if values:
        config_val = values.get("CERT_MAX_CONSECUTIVE_FAILURES", "").strip()
        if config_val and config_val.isdigit():
            max_failures = int(config_val)

    if state.days_remaining <= 0:
        state.state = "manual_intervention"
        state.last_error_code = "EXPIRED"
        state.last_error_message = "证书已过期"
        return

    if state.consecutive_failures >= max_failures:
        state.state = "manual_intervention"
        state.last_error_code = "MAX_FAILURES"
        state.last_error_message = f"连续失败已达 {state.consecutive_failures} 次上限"
        return

    # Check probe health: service, DNS, TLS fingerprints
    probe_ok, probe_error = _probe_is_healthy(state, values or {})
    if not probe_ok:
        state.last_error_code = probe_error
        state.last_error_message = "服务 / DNS / TLS 观测异常"
        if state.days_remaining <= state.urgent_before_days:
            state.state = "urgent"
        else:
            state.state = "degraded"
        return

    if state.days_remaining <= state.urgent_before_days:
        if state.consecutive_failures > 0:
            state.state = "urgent"
            state.last_error_code = "URGENT"
            state.last_error_message = f"剩余 {state.days_remaining:.0f} 天，进入紧急窗口"
        else:
            state.state = "renew_due"
        return

    if state.days_remaining <= state.renew_before_days:
        state.state = "renew_due"
        return

    state.state = "healthy"


def _parse_openssl_date(date_str: str) -> datetime | None:
    """Parse openssl date formats (notBefore=... / notAfter=...)."""
    if not date_str:
        return None

    # openssl formats: "May 19 10:00:00 2026 GMT" or "20260519100000Z"
    formats = [
        "%b %d %H:%M:%S %Y %Z",
        "%b %d %H:%M:%S %Y",
        "%Y%m%d%H%M%S%z",
        "%Y%m%d%H%M%SZ",
    ]
    date_str = date_str.strip()
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_state(state: CertState) -> dict[str, Any]:
    """Produce a redacted dict for local output (no private keys)."""
    d = state.to_dict()
    d.pop("key_path", None)
    d.pop("cert_path", None)
    return d


def _write_local_status(config_path: str, state: CertState) -> None:
    """Write redacted cert-status to local generated/ directory."""
    output_dir = Path(config_path).parent / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"cert-status-{time.strftime('%Y%m%d-%H%M%S')}.json"
    redacted = _redact_state(state)
    out_path.write_text(
        json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _print_status_summary(state: CertState) -> None:
    """Print a human-readable cert-status summary."""
    domain = state.domain
    print(f"=== 证书状态: {domain} ===")

    not_before = state.not_before[:10] if state.not_before else "?"
    not_after = state.not_after[:10] if state.not_after else "?"
    print(f"  有效期: {not_before} → {not_after}")
    print(f"  剩余天数: {state.days_remaining:.0f}/{state.lifetime_days} 天")
    print(f"  续签窗口: {state.renew_before_days} 天")
    print(f"  紧急窗口: {state.urgent_before_days} 天")

    state_indicators = {
        "healthy": "✓ 正常",
        "renew_due": "→ 待续签",
        "verifying": "⋯ 验证中",
        "degraded": "⚠ 降级",
        "urgent": "⚠⚠ 紧急",
        "manual_intervention": "✗ 需人工介入",
        "unknown": "? 未知",
    }
    indicator = state_indicators.get(state.state, state.state)
    print(f"  状态: {indicator}")

    print(f"  服务: {'✓ active' if state.service_active else '✗ inactive'}")
    print(f"  DNS: {'✓ 一致' if state.dns_matches_expected else '✗ 不匹配'}")

    fp = state.file_fingerprint_sha256
    print(f"  本地证书指纹: {fp[:20] + '...' if len(fp) > 20 else fp or '无'}")

    served = state.served_fingerprints
    if served:
        for port, sp in sorted(served.items()):
            match = "✓" if sp == state.file_fingerprint_sha256 else "✗"
            print(f"  端口 {port}: {sp[:20] + '...' if len(sp) > 20 else sp} {match}")

    if state.last_renew_success_at:
        print(f"  上次成功续签: {state.last_renew_success_at}")
    if state.consecutive_failures > 0:
        print(f"  连续失败: {state.consecutive_failures} 次")
    if state.last_error_message:
        print(f"  上次错误: [{state.last_error_code}] {state.last_error_message}")

    print()
    print(f"  HINT: 本地状态已保存到 generated/cert-status-*.json")


# ── cert-renew (Iteration 2) ──────────────────────────────────────────────


CERT_RENEW_SCRIPT = r"""
set -euo pipefail

domain="${DOMAIN}"
cert_dir="/root/cert/${domain}"
fullchain="${cert_dir}/fullchain.pem"
privkey="${cert_dir}/privkey.pem"
acme_home="/root/.acme.sh"
log_dir="${CERT_LOG_DIR}"
state_dir="${CERT_STATE_DIR}"

DRY_RUN="${DRY_RUN:-false}"
FORCE="${FORCE:-false}"

echo "== cert-renew =="
echo "dry_run=${DRY_RUN}"
echo "force=${FORCE}"

# Parse current certificate to decide whether renewal is needed
if [ -f "$fullchain" ]; then
  not_before=$(openssl x509 -in "$fullchain" -noout -startdate 2>/dev/null | sed 's/^notBefore=//')
  not_after=$(openssl x509 -in "$fullchain" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')
  not_after_epoch=$(date -d "$not_after" +%s 2>/dev/null || echo 0)
  not_before_epoch=$(date -d "$not_before" +%s 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  lifetime_days=$(( (not_after_epoch - not_before_epoch) / 86400 ))
  days_remaining=$(( (not_after_epoch - now_epoch) / 86400 ))
  [ "$days_remaining" -lt 0 ] && days_remaining=0
  [ "$lifetime_days" -le 0 ] && lifetime_days=90
  renew_before=$(( (lifetime_days + 2) / 3 ))
  [ "$renew_before" -lt 1 ] && renew_before=1
  echo "days_remaining=${days_remaining}"
  echo "renew_before=${renew_before}"
else
  echo "cert_files=missing"
  days_remaining=0
  renew_before=0
fi

# Pre-check: skip if cert is still far from expiry, unless --force
if [ "${FORCE}" != "true" ] && [ "$days_remaining" -gt "$renew_before" ] && [ "$days_remaining" -gt 0 ]; then
  echo "skip_reason=not_due"
  exit 0
fi

# Dry-run: skip everything that modifies remote
if [ "${DRY_RUN}" = "true" ]; then
  echo "acme_sh_found=$( [ -x "${acme_home}/acme.sh" ] && echo true || echo false)"
  echo "cert_files=$( [ -f "$fullchain" ] && echo present || echo missing)"
  exit 0
fi

mkdir -p "${log_dir}" "${state_dir}"

# 1. Backup current cert
if [ -f "$fullchain" ] || [ -f "$privkey" ]; then
  backup_dir="${cert_dir}/backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  [ -f "$fullchain" ] && cp "$fullchain" "${backup_dir}/" && echo "backup_fullchain=ok"
  [ -f "$privkey" ]  && cp "$privkey" "${backup_dir}/" && echo "backup_privkey=ok"
  echo "backup_dir=${backup_dir}"
fi

# 2. Run acme.sh renew
ACME_CMD="${acme_home}/acme.sh"
if [ ! -x "$ACME_CMD" ]; then
  echo "acme_sh_found=false"
  exit 1
fi
echo "acme_sh_found=true"

if "$ACME_CMD" --renew -d "$domain" --ecc --home "$acme_home" 2>&1; then
  echo "renew_status=renewed"
else
  echo "renew_attempt=renew_failed_trying_issue"
  "$ACME_CMD" --issue -d "$domain" --standalone --ecc --home "$acme_home" 2>&1 || {
    echo "renew_status=failed"
    exit 1
  }
  echo "renew_status=issued"
fi

# 3. Install cert to /root/cert/<domain>/
"$ACME_CMD" --install-cert -d "$domain" --ecc \
  --fullchain-file "$fullchain" \
  --key-file "$privkey" \
  --home "$acme_home" 2>&1
echo "install_status=ok"

# 4. Restart s-ui
systemctl restart s-ui.service
sleep 2
service_state=$(systemctl is-active s-ui.service 2>/dev/null || echo "unknown")
echo "restart_status=${service_state}"

# 5. Re-read certificate metadata (fresh after renew)
if [ -f "$fullchain" ] && [ -f "$privkey" ]; then
  echo "cert_files=present"
  new_fp=$(openssl x509 -in "$fullchain" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
  echo "file_fingerprint_sha256=${new_fp}"
  echo "renewed_not_before=$(openssl x509 -in "$fullchain" -noout -startdate 2>/dev/null | sed 's/^notBefore=//')"
  echo "renewed_not_after=$(openssl x509 -in "$fullchain" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"
else
  echo "cert_files=missing"
  exit 1
fi

# 6. Verify external TLS handshake
for port in ${VERIFY_PORTS}; do
  served_fp=$(echo "Q" | openssl s_client -connect "${domain}:${port}" -servername "$domain" 2>/dev/null | \
    openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
  echo "served_fp_${port}=${served_fp:-missing}"
done

echo "renew_complete=true"
"""


def cmd_renew(values: dict[str, str], config_path: str, dry_run: bool = False, force: bool = False) -> int:
    """Single manual certificate renew cycle.

    Returns:
        0 — success
        1 — pre-check or execution failure
        2 — renew executed but verification failed
    """
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空")
        return 1

    web_port = values.get("WEB_PORT", "2095")
    sub_port = values.get("SUB_PORT", "2096")
    trojan_port = values.get("INBOUND_TROJAN_PORT", "41101")
    verify_ports_str = values.get("CERT_VERIFY_EXTRA_PORTS", trojan_port).strip()
    verify_ports = f"{web_port} {sub_port}"
    if verify_ports_str:
        verify_ports += f" {verify_ports_str}"

    command = _sudo_cmd(
        f"DOMAIN={_shell_quote(domain)} "
        f"DRY_RUN={'true' if dry_run else 'false'} "
        f"FORCE={'true' if force else 'false'} "
        f"CERT_STATE_DIR={STATE_DIR} "
        f"CERT_LOG_DIR={LOG_DIR} "
        f"VERIFY_PORTS={_shell_quote(verify_ports)} "
        f"bash -s <<'CERT_RENEW'\n{CERT_RENEW_SCRIPT}\nCERT_RENEW"
    )
    result = run_ssh(values, command, timeout=300)

    if result.stdout:
        print(result.stdout.rstrip())

    # Check script execution result even for dry-run
    if result.returncode != 0:
        print(f"\nERROR: 续签脚本执行失败 (exit={result.returncode})")
        if result.stderr:
            print(result.stderr.rstrip())
        return 1

    if dry_run:
        print(f"\nOK: cert-renew --dry-run 完成（未修改远端）")
        return 0

    lines = result.stdout.splitlines() if result.stdout else []
    parsed = _parse_probe_output(lines)

    # Handle "not due" skip from script
    skip_reason = parsed.get("skip_reason", "")
    if skip_reason == "not_due":
        days_remaining = parsed.get("days_remaining", "?")
        renew_before = parsed.get("renew_before", "?")
        print(f"\nOK: 证书无需续签（剩余 {days_remaining} 天，续签窗口 {renew_before} 天）")
        print(f"  HINT: 使用 --force 强制续签")
        return 0

    # Verify results
    file_fp = parsed.get("file_fingerprint_sha256", "")
    renew_complete = parsed.get("renew_complete", "false") == "true"
    restart_status = parsed.get("restart_status", "unknown")

    if not renew_complete or restart_status != "active":
        print(f"\nWARN: 续签执行完成，但验证未通过")
        print(f"  服务状态: {restart_status}")
        print(f"  HINT: 运行 cert-status 检查详细状态")
        return 2

    # Check fingerprint consistency
    served: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if line.startswith("served_fp_"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                port_key = parts[0].replace("served_fp_", "")
                served[port_key] = parts[1]
    # Check fingerprint consistency
    all_match = True
    for port in _expected_verify_ports(values):
        sp = served.get(port, "")
        if not sp:
            print(f"  WARN: 端口 {port} TLS 握手失败或未返回证书")
            all_match = False
        elif sp != file_fp:
            print(f"  WARN: 端口 {port} TLS 指纹与文件证书不一致")
            all_match = False

    if all_match:
        print(f"\nOK: 证书续签成功 — {domain}")
        print(f"  HINT: 运行 cert-status 确认最终状态")
        return 0
    else:
        print(f"\nWARN: 续签完成，但对外 TLS 指纹检查不完全一致")
        return 2


# ── cert-supervise (Iteration 4) ──────────────────────────────────────────


def cmd_supervise(values: dict[str, str], config_path: str) -> int:
    """State-machine supervisor: read status, decide action, report result.

    Returns:
        0 — healthy / renew_due (no human action needed)
        2 — degraded
        3 — urgent
        4 — manual_intervention
    """
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空")
        return 1

    web_port = values.get("WEB_PORT", "2095")
    sub_port = values.get("SUB_PORT", "2096")
    extra_ports = values.get("CERT_VERIFY_EXTRA_PORTS", "").strip()

    command = _sudo_cmd(
        f"DOMAIN={_shell_quote(domain)} "
        f"EXPECTED_IP={_shell_quote(values.get('VPS_HOST', ''))} "
        f"WEB_PORT={_shell_quote(web_port)} "
        f"SUB_PORT={_shell_quote(sub_port)} "
        f"EXTRA_VERIFY_PORTS={_shell_quote(extra_ports)} "
        f"CERT_STATE_DIR={STATE_DIR} "
        f"bash -s <<'CERT_SUPERVISE'\n{CERT_PROBE_SCRIPT}\nCERT_SUPERVISE"
    )
    result = run_ssh(values, command, timeout=60)
    if result.returncode != 0:
        print(f"ERROR: SSH 探测失败:\n{result.stderr.rstrip()}")
        return 1

    lines = result.stdout.splitlines() if result.stdout else []
    parsed = _parse_probe_output(lines)

    state = _try_read_state_file(values, domain)
    if state is None:
        state = _build_state_from_probe(parsed, domain)
    else:
        _overlay_probe_onto_state(state, parsed)

    _compute_renew_thresholds(state, values)
    _determine_state(state, values)

    # Write local copy
    _write_local_status(config_path, state)
    _print_status_summary(state)

    if state.state in ("renew_due", "urgent"):
        print(f"\n  状态 '{state.state}': 建议运行 cert-renew 触发续签")

    exit_codes = {
        "healthy": 0,
        "renew_due": 0,
        "verifying": 0,
        "degraded": 2,
        "urgent": 3,
        "manual_intervention": 4,
        "unknown": 1,
    }
    return exit_codes.get(state.state, 1)


# ── install-cert-supervisor (Iteration 3) ─────────────────────────────────


INSTALL_SUPERVISOR_SCRIPT = r"""
set -euo pipefail

domain="${DOMAIN}"
supervisor_dir="${SUPERVISOR_DIR}"
state_dir="${CERT_STATE_DIR}"
log_dir="${CERT_LOG_DIR}"

mkdir -p "${supervisor_dir}" "${state_dir}" "${log_dir}"

STAGE_DIR="${STAGE_DIR:-/tmp/sui-cert-stage}"
if [ -d "$STAGE_DIR" ]; then
  cp "${STAGE_DIR}/cert-supervisor.sh" "${supervisor_dir}/"
  chmod 755 "${supervisor_dir}/cert-supervisor.sh"
  cp "${STAGE_DIR}/cert-supervisor.env" "${supervisor_dir}/"
  chmod 600 "${supervisor_dir}/cert-supervisor.env"
fi

cp "${STAGE_DIR}/sui-cert-supervisor.service" /etc/systemd/system/
cp "${STAGE_DIR}/sui-cert-supervisor.timer" /etc/systemd/system/
systemctl daemon-reload

systemctl enable sui-cert-supervisor.timer
systemctl start sui-cert-supervisor.timer

timer_active=$(systemctl is-active sui-cert-supervisor.timer 2>/dev/null || echo "inactive")
timer_enabled=$(systemctl is-enabled sui-cert-supervisor.timer 2>/dev/null || echo "disabled")
echo "timer_active=${timer_active}"
echo "timer_enabled=${timer_enabled}"

rm -rf "$STAGE_DIR"
echo "install_complete=true"
"""


def cmd_install_supervisor(values: dict[str, str], config_path: str) -> int:
    """Install the remote certificate supervisor (systemd timer + service + script).

    Returns:
        0 — installation successful
        1 — upload, enable, or first-run check failed
    """
    domain = values.get("DOMAIN", "")
    if not domain:
        print("ERROR: DOMAIN 为空")
        return 1

    # Check if auto-renew is enabled
    if values.get("CERT_AUTORENEW_ENABLED", "true").lower() != "true":
        print("INFO: CERT_AUTORENEW_ENABLED=false，跳过 supervisor 安装")
        print("  HINT: 将 CERT_AUTORENEW_ENABLED=\"true\" 后重试")
        return 0

    env_content = _build_supervisor_env(values)
    supervisor_sh = _render_supervisor_sh(values)
    service_unit = _render_systemd_service(values)
    timer_unit = _render_systemd_timer(values)

    stage_dir = "/tmp/sui-cert-stage"
    host = values["VPS_HOST"]
    user = values.get("SSH_USER", "ubuntu")
    port = values.get("SSH_PORT", "22")
    key_path = values["SSH_KEY_PATH"]

    mkdir_result = run_ssh(values, f"mkdir -p {stage_dir}", timeout=15)
    if mkdir_result.returncode != 0:
        print(f"ERROR: 无法在远端创建临时目录: {mkdir_result.stderr}")
        return 1

    files_to_upload = {
        "cert-supervisor.sh": supervisor_sh,
        "cert-supervisor.env": env_content,
        "sui-cert-supervisor.service": service_unit,
        "sui-cert-supervisor.timer": timer_unit,
    }

    remote_stage = f"{user}@{host}:{stage_dir}/"
    scp_base = [
        "scp",
        "-i", key_path,
        "-P", port,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
    ]

    import tempfile
    for filename, content in files_to_upload.items():
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=f".{filename}", delete=False) as f:
                f.write(content)
                local_tmp = f.name

            scp_cmd = scp_base + [local_tmp, f"{remote_stage}{filename}"]
            subprocess.run(scp_cmd, check=True, capture_output=True, timeout=30)
            Path(local_tmp).unlink(missing_ok=True)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR: 上传 {filename} 失败: {exc.stderr.decode()}")
            return 1
        except Exception as exc:
            print(f"ERROR: 上传 {filename} 异常: {exc}")
            return 1

    install_cmd = _sudo_cmd(
        f"DOMAIN={_shell_quote(domain)} "
        f"SUPERVISOR_DIR={_shell_quote(SUPERVISOR_DIR)} "
        f"CERT_STATE_DIR={_shell_quote(STATE_DIR)} "
        f"CERT_LOG_DIR={_shell_quote(LOG_DIR)} "
        f"STAGE_DIR={_shell_quote(stage_dir)} "
        f"bash -s <<'INSTALL_SUPERVISOR'\n{INSTALL_SUPERVISOR_SCRIPT}\nINSTALL_SUPERVISOR"
    )
    install_result = run_ssh(values, install_cmd, timeout=60)

    if install_result.stdout:
        print(install_result.stdout.rstrip())
    if install_result.stderr:
        print(f"STDERR: {install_result.stderr.rstrip()}")

    if install_result.returncode != 0:
        print(f"\nERROR: supervisor 安装失败")
        return 1

    check_cmd = "systemctl is-active sui-cert-supervisor.timer 2>/dev/null || echo 'inactive'"
    check_result = run_ssh(values, check_cmd, timeout=15)

    if "active" in (check_result.stdout or ""):
        # ── First-run check: execute the supervisor service immediately ──
        print("  Running first check...")
        first_run = run_ssh(
            values,
            _sudo_cmd("systemctl start sui-cert-supervisor.service"),
            timeout=120,
        )
        if first_run.returncode != 0:
            print(f"\nERROR: supervisor 已安装，但首次检查执行失败")
            if first_run.stderr:
                print(first_run.stderr.rstrip())
            return 1

        # Verify state file was generated
        state_check = run_ssh(
            values,
            _sudo_cmd(f"test -s {STATE_FILE}"),
            timeout=15,
        )
        if state_check.returncode != 0:
            print(f"\nERROR: supervisor 首次检查后未生成状态文件")
            print(f"  HINT: 检查远程日志 {LOG_DIR}/cert-supervisor.log")
            return 1

        print(f"\nOK: cert-supervisor 安装完成 — {domain}")
        print(f"  Timer: active, 每 12 小时自动检查证书")
        print(f"  HINT: 运行 cert-status 查看初始状态")
        return 0
    else:
        print(f"\nWARN: supervisor 安装完成，但 timer 未激活")
        return 1


def _build_supervisor_env(values: dict[str, str]) -> str:
    """Build the cert-supervisor.env file content for the remote VPS."""
    return f"""# Certificate supervisor config — generated by sui-deploy install-cert-supervisor
DOMAIN={values.get("DOMAIN", "")}
CERT_DIR=/root/cert/{values.get("DOMAIN", "")}
FULLCHAIN=/root/cert/{values.get("DOMAIN", "")}/fullchain.pem
PRIVKEY=/root/cert/{values.get("DOMAIN", "")}/privkey.pem
WEB_PORT={values.get("WEB_PORT", "2095")}
SUB_PORT={values.get("SUB_PORT", "2096")}
CERT_RENEW_BEFORE_DAYS={values.get("CERT_RENEW_BEFORE_DAYS", "")}
CERT_RENEW_URGENT_BEFORE_DAYS={values.get("CERT_RENEW_URGENT_BEFORE_DAYS", "")}
CERT_MAX_CONSECUTIVE_FAILURES={values.get("CERT_MAX_CONSECUTIVE_FAILURES", "5")}
CERT_RETRY_BACKOFF_MINUTES={values.get("CERT_RETRY_BACKOFF_MINUTES", "60")}
CERT_VERIFY_EXTRA_PORTS={values.get("CERT_VERIFY_EXTRA_PORTS", "")}
CERT_AUTORENEW_ENABLED={values.get("CERT_AUTORENEW_ENABLED", "true")}
STATE_DIR={STATE_DIR}
LOG_DIR={LOG_DIR}
ACME_HOME=/root/.acme.sh
"""


def _render_supervisor_sh(values: dict[str, str]) -> str:
    """Render the remote cert-supervisor.sh script.

    The write_state() function is defined BEFORE any calls to it,
    and all variables it references are initialized before first use.
    After a successful renew + restart the script re-reads certificate
    metadata so the state file always contains fresh values.
    """
    return r"""#!/usr/bin/env bash
# Certificate supervisor — single check-and-renew cycle for one domain.
# Installed by sui-deploy install-cert-supervisor.
set -euo pipefail

CONFIG="/usr/local/s-ui-deployer/cert-supervisor.env"
[ -f "$CONFIG" ] && source "$CONFIG"

DOMAIN="${DOMAIN:-}"
FULLCHAIN="${FULLCHAIN:-/root/cert/$DOMAIN/fullchain.pem}"
PRIVKEY="${PRIVKEY:-/root/cert/$DOMAIN/privkey.pem}"
WEB_PORT="${WEB_PORT:-2095}"
SUB_PORT="${SUB_PORT:-2096}"
STATE_DIR="${STATE_DIR:-/var/lib/s-ui-deployer}"
LOG_DIR="${LOG_DIR:-/var/log/s-ui-deployer}"
ACME_HOME="${ACME_HOME:-/root/.acme.sh}"
CERT_MAX_CONSECUTIVE_FAILURES="${CERT_MAX_CONSECUTIVE_FAILURES:-5}"
CERT_RETRY_BACKOFF_MINUTES="${CERT_RETRY_BACKOFF_MINUTES:-60}"
CERT_VERIFY_EXTRA_PORTS="${CERT_VERIFY_EXTRA_PORTS:-}"

mkdir -p "$STATE_DIR" "$LOG_DIR"
LOG_FILE="${LOG_DIR}/cert-supervisor.log"

# If auto-renew is disabled, exit silently
AUTORENEW="${CERT_AUTORENEW_ENABLED:-true}"
if [ "$AUTORENEW" != "true" ]; then
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] cert-supervisor: CERT_AUTORENEW_ENABLED=false, skipping" >> "$LOG_FILE"
    exit 0
fi

log() {
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG_FILE"
}

# ── Read previous state (read BEFORE write_state is first called) ──
PREV_LAST_RENEW_AT=""
PREV_LAST_SUCCESS_AT=""
PREV_DNS_MATCHES=true
PREV_SERVED_FPS="{}"
if [ -f "$STATE_DIR/cert-state.json" ]; then
    export STATE_DIR
    python3 <<'PYEOF' 2>/dev/null || true
import json, os
d = json.load(open(os.environ['STATE_DIR'] + '/cert-state.json'))
with open('/tmp/.sui-cert-prev-state', 'w') as f:
    f.write(f"PREV_LAST_RENEW_AT={d.get('last_renew_attempt_at','')}\n")
    f.write(f"PREV_LAST_SUCCESS_AT={d.get('last_renew_success_at','')}\n")
    f.write(f"PREV_DNS_MATCHES={str(d.get('dns_matches_expected', True)).lower()}\n")
    f.write(f"PREV_SERVED_FPS={json.dumps(d.get('served_fingerprints', {}))}\n")
PYEOF
    [ -f /tmp/.sui-cert-prev-state ] && source /tmp/.sui-cert-prev-state && rm -f /tmp/.sui-cert-prev-state
fi

# ── write_state — defined BEFORE any calls ──
# Semantics:
#   - last_renew_attempt_at / last_renew_success_at are ONLY updated when
#     a real renew attempt (or success) occurs. Healthy/backoff paths
#     preserve the previous values.
#   - dns_matches_expected / served_fingerprints preserve the last observed
#     values from the previous probe. The supervisor inner loop does not
#     re-probe DNS/TLS (that's the outer loop's job), so it keeps the
#     most recent known values rather than writing hardcoded defaults.
write_state() {
    local now_iso
    now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local renew_attempt="${RENEW_ATTEMPT_AT:-${PREV_LAST_RENEW_AT:-}}"
    local renew_success="${RENEW_SUCCESS_AT:-${PREV_LAST_SUCCESS_AT:-}}"
    local dns_match="${PREV_DNS_MATCHES:-true}"
    local served_fps="${PREV_SERVED_FPS:-{}}"
    cat > "$STATE_DIR/cert-state.json" <<STATE_EOF
{
    "domain": "${DOMAIN}",
    "cert_path": "${FULLCHAIN}",
    "key_path": "${PRIVKEY}",
    "not_before": "${NOT_BEFORE:-}",
    "not_after": "${NOT_AFTER:-}",
    "lifetime_days": ${LIFETIME_DAYS:-90},
    "days_remaining": ${DAYS_REMAINING:-0},
    "renew_before_days": ${RENEW_BEFORE:-30},
    "urgent_before_days": ${URGENT_BEFORE:-15},
    "state": "${STATE:-unknown}",
    "service_active": $( [ "${SERVICE_ACTIVE:-inactive}" = "active" ] && echo true || echo false),
    "dns_matches_expected": $dns_match,
    "file_fingerprint_sha256": "${FILE_FP:-}",
    "served_fingerprints": $served_fps,
    "last_check_at": "$now_iso",
    "last_renew_attempt_at": "${renew_attempt}",
    "last_renew_success_at": "${renew_success}",
    "consecutive_failures": ${CONSECUTIVE_FAILURES:-0},
    "last_error_code": "$( [ "${STATE:-}" = "healthy" ] && echo '' || echo 'RENEW_FAILED')",
    "last_error_message": "$( [ "${STATE:-}" = "healthy" ] && echo '' || echo 'Renewal failed')"
}
STATE_EOF
}

log "=== cert-supervisor check ==="

# Initialize all variables that write_state references
STATE="healthy"
CONSECUTIVE_FAILURES=0
SERVICE_ACTIVE="active"
NOT_BEFORE=""
NOT_AFTER=""
FILE_FP=""
LIFETIME_DAYS=90
DAYS_REMAINING=0
RENEW_BEFORE=30
URGENT_BEFORE=15
PREV_RENEW_AT=""
LAST_RENEW_AT=""

# 1. Parse current certificate
if [ ! -f "$FULLCHAIN" ]; then
    log "ERROR: 证书文件不存在: $FULLCHAIN"
    STATE="manual_intervention"
    write_state
    exit 1
fi

NOT_BEFORE=$(openssl x509 -in "$FULLCHAIN" -noout -startdate 2>/dev/null | sed 's/^notBefore=//')
NOT_AFTER=$(openssl x509 -in "$FULLCHAIN" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')
FILE_FP=$(openssl x509 -in "$FULLCHAIN" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')

# Calculate days remaining
NOT_AFTER_EPOCH=$(date -d "$NOT_AFTER" +%s 2>/dev/null || echo 0)
NOT_BEFORE_EPOCH=$(date -d "$NOT_BEFORE" +%s 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
LIFETIME_DAYS=$(( (NOT_AFTER_EPOCH - NOT_BEFORE_EPOCH) / 86400 ))
DAYS_REMAINING=$(( (NOT_AFTER_EPOCH - NOW_EPOCH) / 86400 ))
[ "$DAYS_REMAINING" -lt 0 ] && DAYS_REMAINING=0
[ "$LIFETIME_DAYS" -le 0 ] && LIFETIME_DAYS=90

RENEW_BEFORE=${CERT_RENEW_BEFORE_DAYS:-$(( (LIFETIME_DAYS + 2) / 3 ))}
URGENT_BEFORE=${CERT_RENEW_URGENT_BEFORE_DAYS:-$(( (LIFETIME_DAYS + 5) / 6 ))}
[ "$RENEW_BEFORE" -lt 1 ] && RENEW_BEFORE=1
[ "$URGENT_BEFORE" -lt 1 ] && URGENT_BEFORE=1

log "Domain: $DOMAIN"
log "Remaining: ${DAYS_REMAINING}/${LIFETIME_DAYS} days"
log "Renew threshold: ${RENEW_BEFORE}d, Urgent: ${URGENT_BEFORE}d"

# 2. Check if renewal is needed
if [ "$DAYS_REMAINING" -gt "$RENEW_BEFORE" ]; then
    log "State: healthy — no action needed"
    STATE="healthy"
    CONSECUTIVE_FAILURES=0
    write_state
    exit 0
fi

# 3. Read previous state for failure tracking
PREV_STATE=""
PREV_FAILURES=0
PREV_RENEW_AT=""
if [ -f "$STATE_DIR/cert-state.json" ]; then
    PREV_STATE=$(python3 -c "import json; d=json.load(open('$STATE_DIR/cert-state.json')); print(d.get('state',''))" 2>/dev/null || echo "")
    PREV_FAILURES=$(python3 -c "import json; d=json.load(open('$STATE_DIR/cert-state.json')); print(d.get('consecutive_failures',0))" 2>/dev/null || echo "0")
    PREV_RENEW_AT=$(python3 -c "import json; d=json.load(open('$STATE_DIR/cert-state.json')); print(d.get('last_renew_attempt_at',''))" 2>/dev/null || echo "")
fi
CONSECUTIVE_FAILURES=$PREV_FAILURES

# 4. Check backoff
if [ "$DAYS_REMAINING" -gt "$URGENT_BEFORE" ] && [ -n "$PREV_RENEW_AT" ]; then
    PREV_EPOCH=$(date -d "$PREV_RENEW_AT" +%s 2>/dev/null || echo 0)
    ELAPSED=$(( (NOW_EPOCH - PREV_EPOCH) / 60 ))
    if [ "$ELAPSED" -lt "$CERT_RETRY_BACKOFF_MINUTES" ] && [ "$CONSECUTIVE_FAILURES" -gt 0 ]; then
        log "State: degraded — 退避中（上次尝试 ${ELAPSED} 分钟前）"
        STATE="degraded"
        write_state
        exit 0
    fi
fi

# 5. Execute renew
log "State: renew_due — 开始续签"
BACKUP_DIR="/root/cert/$DOMAIN/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp "$FULLCHAIN" "$BACKUP_DIR/" 2>/dev/null || true
cp "$PRIVKEY" "$BACKUP_DIR/" 2>/dev/null || true

ACME_CMD="$ACME_HOME/acme.sh"
RENEW_OK=false

if [ -x "$ACME_CMD" ]; then
    log "Running acme.sh --renew..."
    if "$ACME_CMD" --renew -d "$DOMAIN" --ecc --home "$ACME_HOME" >> "$LOG_FILE" 2>&1; then
        log "acme.sh: renewed"
    else
        log "acme.sh: renew failed, trying --issue..."
        if "$ACME_CMD" --issue -d "$DOMAIN" --standalone --ecc --home "$ACME_HOME" >> "$LOG_FILE" 2>&1; then
            log "acme.sh: issued (recovery)"
        else
            log "acme.sh: issue also failed"
        fi
    fi

    log "Installing cert..."
    "$ACME_CMD" --install-cert -d "$DOMAIN" --ecc \
        --fullchain-file "$FULLCHAIN" \
        --key-file "$PRIVKEY" \
        --home "$ACME_HOME" >> "$LOG_FILE" 2>&1 && RENEW_OK=true
fi

if [ "$RENEW_OK" = false ]; then
    RENEW_ATTEMPT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    log "ERROR: 证书安装失败"
    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
    STATE="degraded"
    if [ "$CONSECUTIVE_FAILURES" -ge "$CERT_MAX_CONSECUTIVE_FAILURES" ]; then
        STATE="manual_intervention"
    fi
    write_state
    exit 1
fi

# 6. Restart S-UI
log "Restarting s-ui.service..."
systemctl restart s-ui.service 2>&1 | tee -a "$LOG_FILE" || true
SERVICE_ACTIVE="inactive"
sleep 2

# 7. Verify — re-read certificate metadata AFTER restart
SERVICE_ACTIVE=$(systemctl is-active s-ui.service 2>/dev/null || echo "inactive")
if [ "$SERVICE_ACTIVE" != "active" ]; then
    RENEW_ATTEMPT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    log "ERROR: s-ui.service 重启后未 active"
    cp "$BACKUP_DIR/fullchain.pem" "$FULLCHAIN" 2>/dev/null || true
    cp "$BACKUP_DIR/privkey.pem" "$PRIVKEY" 2>/dev/null || true
    systemctl restart s-ui.service 2>/dev/null || true
    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
    STATE="manual_intervention"
    write_state
    exit 1
fi

# Re-read fresh certificate metadata after successful restart
NOT_BEFORE=$(openssl x509 -in "$FULLCHAIN" -noout -startdate 2>/dev/null | sed 's/^notBefore=//')
NOT_AFTER=$(openssl x509 -in "$FULLCHAIN" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')
FILE_FP=$(openssl x509 -in "$FULLCHAIN" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
NOT_AFTER_EPOCH=$(date -d "$NOT_AFTER" +%s 2>/dev/null || echo 0)
NOT_BEFORE_EPOCH=$(date -d "$NOT_BEFORE" +%s 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
LIFETIME_DAYS=$(( (NOT_AFTER_EPOCH - NOT_BEFORE_EPOCH) / 86400 ))
DAYS_REMAINING=$(( (NOT_AFTER_EPOCH - NOW_EPOCH) / 86400 ))
[ "$DAYS_REMAINING" -lt 0 ] && DAYS_REMAINING=0
[ "$LIFETIME_DAYS" -le 0 ] && LIFETIME_DAYS=90
RENEW_BEFORE=${CERT_RENEW_BEFORE_DAYS:-$(( (LIFETIME_DAYS + 2) / 3 ))}
URGENT_BEFORE=${CERT_RENEW_URGENT_BEFORE_DAYS:-$(( (LIFETIME_DAYS + 5) / 6 ))}
[ "$RENEW_BEFORE" -lt 1 ] && RENEW_BEFORE=1
[ "$URGENT_BEFORE" -lt 1 ] && URGENT_BEFORE=1

# Verify external TLS on key ports
ALL_VERIFIED=true
for port in $WEB_PORT $SUB_PORT $CERT_VERIFY_EXTRA_PORTS; do
    [ -z "$port" ] && continue
    SERVED_FP=$(echo "Q" | openssl s_client -connect "${DOMAIN}:${port}" -servername "$DOMAIN" 2>/dev/null | \
        openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//')
    if [ -z "$SERVED_FP" ]; then
        log "WARN: 端口 ${port} TLS 握手失败或未返回证书"
        ALL_VERIFIED=false
    elif [ "$SERVED_FP" != "$FILE_FP" ]; then
        log "WARN: 端口 ${port} TLS 指纹不匹配 — 服务 ${SERVED_FP:0:20}... 文件 ${FILE_FP:0:20}..."
        ALL_VERIFIED=false
    fi
done

LAST_RENEW_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RENEW_ATTEMPT_AT="$LAST_RENEW_AT"

if [ "$ALL_VERIFIED" = true ]; then
    RENEW_SUCCESS_AT="$LAST_RENEW_AT"
    log "OK: 续签成功 — 所有端口指纹一致"
    CONSECUTIVE_FAILURES=0
    STATE="healthy"
else
    log "WARN: 续签完成但部分端口指纹异常"
    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
    STATE="degraded"
fi

write_state
"""


def _render_systemd_service(values: dict[str, str]) -> str:
    """Render the systemd service unit."""
    return """[Unit]
Description=S-UI Certificate Supervisor — single check-and-renew cycle
Documentation=https://github.com/alireza0/s-ui
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/s-ui-deployer/cert-supervisor.sh
User=root
Group=root
StandardOutput=journal
StandardError=journal
"""


def _render_systemd_timer(values: dict[str, str]) -> str:
    """Render the systemd timer unit."""
    interval = values.get("CERT_SUPERVISOR_INTERVAL", "12h")
    return f"""[Unit]
Description=S-UI Certificate Supervisor — periodic check timer
Documentation=https://github.com/alireza0/s-ui

[Timer]
OnBootSec=10min
OnUnitActiveSec={interval}
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
"""


# ── Shared helpers ────────────────────────────────────────────────────────


def _shell_quote(value: str) -> str:
    """Shell-safe quoting for variable interpolation."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _sudo_cmd(command: str) -> str:
    """Wrap a command in sudo with clean root environment.

    Clears SUDO_* vars so acme.sh doesn't refuse to run.
    """
    return (
        "sudo env -u SUDO_USER -u SUDO_UID -u SUDO_GID -u SUDO_COMMAND "
        "HOME=/root " + command
    )
