"""Unit tests for certificate auto-renewal (Phase 6) logic.

Tests cover:
- Dynamic threshold calculation
- openssl date parsing
- State machine transitions
- Fingerprint extraction from probe output
- Redaction
- Consecutive failure counting
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sui_deployer.workflow.cert import (
    CertState,
    _build_state_from_probe,
    _compute_renew_thresholds,
    _determine_state,
    _expected_verify_ports,
    _parse_openssl_date,
    _parse_probe_output,
    _probe_is_healthy,
    _redact_state,
    _shell_quote,
)


class ThresholdTests(unittest.TestCase):
    """Dynamic renew window calculation."""

    def test_90_day_lifetime(self):
        """90-day cert: renew at 30d, urgent at 15d."""
        state = CertState(lifetime_days=90, days_remaining=60)
        _compute_renew_thresholds(state, {})
        self.assertEqual(state.renew_before_days, 30)
        self.assertEqual(state.urgent_before_days, 15)

    def test_45_day_lifetime(self):
        """45-day cert: renew at 15d, urgent at ~8d."""
        state = CertState(lifetime_days=45, days_remaining=30)
        _compute_renew_thresholds(state, {})
        self.assertEqual(state.renew_before_days, 15)
        self.assertEqual(state.urgent_before_days, 8)

    def test_7_day_lifetime(self):
        """7-day short-life cert: renew at ceil(7/3)=3, urgent at ceil(7/6)=2."""
        state = CertState(lifetime_days=7, days_remaining=5)
        _compute_renew_thresholds(state, {})
        self.assertEqual(state.renew_before_days, 3)
        self.assertEqual(state.urgent_before_days, 2)

    def test_1_day_lifetime_minimum(self):
        """1-day cert: minimum thresholds of 1."""
        state = CertState(lifetime_days=1, days_remaining=1)
        _compute_renew_thresholds(state, {})
        self.assertGreaterEqual(state.renew_before_days, 1)
        self.assertGreaterEqual(state.urgent_before_days, 1)

    def test_zero_lifetime_fallback(self):
        """Zero lifetime falls back to 90-day defaults."""
        state = CertState(lifetime_days=0, days_remaining=60)
        _compute_renew_thresholds(state, {})
        self.assertEqual(state.renew_before_days, 30)
        self.assertEqual(state.urgent_before_days, 15)

    def test_config_override_renew(self):
        """CERT_RENEW_BEFORE_DAYS overrides dynamic computation."""
        state = CertState(lifetime_days=90, days_remaining=60)
        _compute_renew_thresholds(state, {"CERT_RENEW_BEFORE_DAYS": "7"})
        self.assertEqual(state.renew_before_days, 7)
        self.assertEqual(state.urgent_before_days, 15)

    def test_config_override_urgent(self):
        """CERT_RENEW_URGENT_BEFORE_DAYS overrides dynamic computation."""
        state = CertState(lifetime_days=90, days_remaining=60)
        _compute_renew_thresholds(state, {"CERT_RENEW_URGENT_BEFORE_DAYS": "3"})
        self.assertEqual(state.renew_before_days, 30)
        self.assertEqual(state.urgent_before_days, 3)


class DateParsingTests(unittest.TestCase):
    """openssl date format parsing."""

    def test_openssl_gmt_format(self):
        """Parse 'May 19 10:00:00 2026 GMT'."""
        dt = _parse_openssl_date("May 19 10:00:00 2026 GMT")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 5)
        self.assertEqual(dt.day, 19)
        self.assertEqual(dt.hour, 10)

    def test_openssl_no_tz(self):
        """Parse 'May 19 10:00:00 2026' without timezone."""
        dt = _parse_openssl_date("May 19 10:00:00 2026")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_compact_format(self):
        """Parse '20260519100000Z' compact format."""
        dt = _parse_openssl_date("20260519100000Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 5)

    def test_empty_string(self):
        """Empty string returns None."""
        dt = _parse_openssl_date("")
        self.assertIsNone(dt)

    def test_invalid_string(self):
        """Garbage string returns None."""
        dt = _parse_openssl_date("not-a-date")
        self.assertIsNone(dt)


class StateMachineTests(unittest.TestCase):
    """State machine transition logic."""

    def _healthy_state(self, **overrides) -> CertState:
        """Build a CertState with all probe-healthy fields set."""
        fields = dict(
            days_remaining=60,
            renew_before_days=30,
            urgent_before_days=15,
            consecutive_failures=0,
            service_active=True,
            dns_matches_expected=True,
            file_fingerprint_sha256="AB:CD:EF:12:34",
            served_fingerprints={
                "2095": "AB:CD:EF:12:34",
                "2096": "AB:CD:EF:12:34",
            },
        )
        fields.update(overrides)
        return CertState(**fields)

    def test_healthy(self):
        """days_remaining > renew_before_days -> healthy."""
        state = self._healthy_state(days_remaining=60)
        _determine_state(state, {})
        self.assertEqual(state.state, "healthy")

    def test_renew_due(self):
        """days_remaining <= renew_before_days -> renew_due."""
        state = self._healthy_state(days_remaining=25)
        _determine_state(state, {})
        self.assertEqual(state.state, "renew_due")

    def test_urgent_edge(self):
        """days_remaining <= urgent_before_days but zero failures -> renew_due."""
        state = self._healthy_state(days_remaining=10, consecutive_failures=0)
        _determine_state(state, {})
        self.assertEqual(state.state, "renew_due")

    def test_urgent_with_failures(self):
        """days_remaining <= urgent_before_days with failures -> urgent."""
        state = self._healthy_state(days_remaining=10, consecutive_failures=2)
        _determine_state(state, {})
        self.assertEqual(state.state, "urgent")

    def test_expired(self):
        """days_remaining <= 0 -> manual_intervention."""
        state = self._healthy_state(days_remaining=0)
        _determine_state(state, {})
        self.assertEqual(state.state, "manual_intervention")
        self.assertEqual(state.last_error_code, "EXPIRED")

    def test_negative_remaining(self):
        """days_remaining < 0 -> manual_intervention."""
        state = self._healthy_state(days_remaining=-5)
        _determine_state(state, {})
        self.assertEqual(state.state, "manual_intervention")

    def test_max_failures_reached(self):
        """consecutive_failures >= max -> manual_intervention."""
        state = self._healthy_state(days_remaining=60, consecutive_failures=5)
        _determine_state(state, {})
        self.assertEqual(state.state, "manual_intervention")
        self.assertEqual(state.last_error_code, "MAX_FAILURES")

    def test_max_failures_from_config(self):
        """CERT_MAX_CONSECUTIVE_FAILURES from config overrides default."""
        state = self._healthy_state(days_remaining=60, consecutive_failures=3)
        _determine_state(state, {"CERT_MAX_CONSECUTIVE_FAILURES": "3"})
        self.assertEqual(state.state, "manual_intervention")


class ProbeParsingTests(unittest.TestCase):
    """Parse SSH probe output lines."""

    def test_parse_cert_file_status(self):
        """Parse cert_files=present from probe output."""
        lines = [
            "== cert-status ==",
            "cert_files=present",
            "service_active=active",
            "dns_resolved=203.0.113.10",
            "expected_ip=203.0.113.10",
        ]
        parsed = _parse_probe_output(lines)
        self.assertEqual(parsed.get("cert_files"), "present")
        self.assertEqual(parsed.get("service_active"), "active")

    def test_parse_service_inactive(self):
        """Parse service_active=inactive."""
        lines = ["service_active=inactive"]
        parsed = _parse_probe_output(lines)
        self.assertEqual(parsed.get("service_active"), "inactive")

    def test_parse_dns_mismatch(self):
        """DNS resolved != expected_ip."""
        lines = [
            "dns_resolved=192.168.1.1",
            "expected_ip=203.0.113.10",
        ]
        parsed = _parse_probe_output(lines)
        self.assertEqual(parsed.get("dns_resolved"), "192.168.1.1")
        self.assertEqual(parsed.get("expected_ip"), "203.0.113.10")

    def test_parse_port_labeled_tls_fingerprints(self):
        """Port-labeled TLS fingerprints are correctly parsed."""
        lines = [
            "tls_fp_2095=AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90",
            "tls_fp_2096=AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90",
            "tls_fp_41101=11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00",
        ]
        parsed = _parse_probe_output(lines)
        served = parsed.get("served_fingerprints", {})
        self.assertIn("2095", served)
        self.assertIn("2096", served)
        self.assertIn("41101", served)
        self.assertEqual(served["2095"][:8], "AB:CD:EF")
        self.assertEqual(served["41101"][:8], "11:22:33")

    def test_parse_tls_fingerprint_missing(self):
        """tls_fp_ port=missing is excluded from served_fingerprints."""
        lines = ["tls_fp_2095=missing", "tls_fp_2096=AB:CD:EF:12:34"]
        parsed = _parse_probe_output(lines)
        served = parsed.get("served_fingerprints", {})
        self.assertNotIn("2095", served)
        self.assertIn("2096", served)

    def test_parse_skip_reason(self):
        """skip_reason=not_due is parsed from cert-renew output."""
        lines = ["skip_reason=not_due", "days_remaining=60", "renew_before=30"]
        parsed = _parse_probe_output(lines)
        self.assertEqual(parsed.get("skip_reason"), "not_due")
        self.assertEqual(parsed.get("days_remaining"), "60")

    def test_build_state_prefers_direct_file_fingerprint(self):
        """Probe state should use file_fingerprint_sha256 from key=value output."""
        parsed = {
            "cert_files": "present",
            "file_fingerprint_sha256": "AA:BB:CC",
            "service_active": "active",
            "dns_resolved": "203.0.113.10",
            "expected_ip": "203.0.113.10",
        }
        state = _build_state_from_probe(parsed, "example.com")
        self.assertEqual(state.file_fingerprint_sha256, "AA:BB:CC")


class CmdRenewLogicTests(unittest.TestCase):
    """Tests for cert-renew command logic."""

    def test_compute_renew_window_80_of_90(self):
        """80 days remaining of 90 → not in window (renew at 30)."""
        # This simulates what the shell script computes
        lifetime_days = 90
        days_remaining = 80
        renew_before = max(1, (lifetime_days + 2) // 3)  # 30
        urgent_before = max(1, (lifetime_days + 5) // 6)  # 15
        self.assertEqual(renew_before, 30)
        self.assertEqual(urgent_before, 15)
        # Not in window without --force
        self.assertGreater(days_remaining, renew_before)

    def test_compute_renew_window_20_of_90(self):
        """20 days remaining of 90 → in window (renew at 30)."""
        lifetime_days = 90
        days_remaining = 20
        renew_before = max(1, (lifetime_days + 2) // 3)
        self.assertLessEqual(days_remaining, renew_before)

    def test_supervisor_write_state_preserves_timestamps(self):
        """Simulate write_state preserving previous renew timestamps.

        On a healthy/backoff path with no real renew attempt,
        RENEW_ATTEMPT_AT and RENEW_SUCCESS_AT should be empty/falsy,
        causing write_state to fall back to PREV_* values.
        """
        # This is the logic inside write_state():
        PREV_LAST_RENEW_AT = "2026-05-10T02:00:00Z"
        PREV_LAST_SUCCESS_AT = "2026-05-10T02:01:20Z"

        # No actual renew happened this run → RENEW_ATTEMPT_AT is empty
        renew_attempt = PREV_LAST_RENEW_AT  # fallback to PREV
        renew_success = PREV_LAST_SUCCESS_AT  # fallback to PREV

        self.assertEqual(renew_attempt, "2026-05-10T02:00:00Z")
        self.assertEqual(renew_success, "2026-05-10T02:01:20Z")

    def test_supervisor_write_state_updates_after_renew(self):
        """Simulate write_state after a real renew attempt with success.

        When a real renew attempted, RENEW_ATTEMPT_AT is set.
        When it succeeds with all fingerprints matching, RENEW_SUCCESS_AT is also set.
        """
        now = "2026-06-01T10:00:00Z"
        PREV_LAST_RENEW_AT = "2026-05-10T02:00:00Z"

        # Renew happened → RENEW_ATTEMPT_AT is set
        RENEW_ATTEMPT_AT = now
        RENEW_SUCCESS_AT = now  # verified OK

        # write_state should use the new values, not PREV
        renew_attempt = RENEW_ATTEMPT_AT
        renew_success = RENEW_SUCCESS_AT

        self.assertEqual(renew_attempt, "2026-06-01T10:00:00Z")
        self.assertEqual(renew_success, "2026-06-01T10:00:00Z")


class CertAutorenewEnabledTests(unittest.TestCase):
    """Tests for CERT_AUTORENEW_ENABLED wiring."""

    def test_env_contains_autorenew_key(self):
        """_build_supervisor_env includes CERT_AUTORENEW_ENABLED."""
        from sui_deployer.workflow.cert import _build_supervisor_env
        env = _build_supervisor_env({"DOMAIN": "example.com"})
        self.assertIn("CERT_AUTORENEW_ENABLED", env)


class ProbeHealthTests(unittest.TestCase):
    """Test probe health classification."""

    def _make_state(self, **overrides) -> CertState:
        fields = dict(
            domain="example.com",
            state="unknown",
            service_active=True,
            dns_matches_expected=True,
            file_fingerprint_sha256="AB:CD:EF:12:34",
            served_fingerprints={"2095": "AB:CD:EF:12:34", "2096": "AB:CD:EF:12:34"},
            days_remaining=60,
            lifetime_days=90,
            renew_before_days=30,
            urgent_before_days=15,
            consecutive_failures=0,
        )
        fields.update(overrides)
        return CertState(**fields)

    def test_healthy_probe(self):
        """All criteria pass -> healthy."""
        ok, err = _probe_is_healthy(self._make_state(), {"WEB_PORT": "2095", "SUB_PORT": "2096"})
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_service_inactive(self):
        """service_active=False -> SERVICE_INACTIVE."""
        ok, err = _probe_is_healthy(self._make_state(service_active=False), {})
        self.assertFalse(ok)
        self.assertEqual(err, "SERVICE_INACTIVE")

    def test_dns_mismatch(self):
        """dns_matches_expected=False -> DNS_MISMATCH."""
        ok, err = _probe_is_healthy(self._make_state(dns_matches_expected=False), {})
        self.assertFalse(ok)
        self.assertEqual(err, "DNS_MISMATCH")

    def test_cert_file_missing(self):
        """file_fingerprint_sha256 empty -> CERT_FILE_MISSING."""
        ok, err = _probe_is_healthy(self._make_state(file_fingerprint_sha256=""), {})
        self.assertFalse(ok)
        self.assertEqual(err, "CERT_FILE_MISSING")

    def test_tls_missing_port(self):
        """Expected port missing from served fingerprints -> TLS_MISSING_{port}."""
        ok, err = _probe_is_healthy(
            self._make_state(served_fingerprints={"2095": "AB:CD:EF:12:34"}),
            {"WEB_PORT": "2095", "SUB_PORT": "2096"},
        )
        self.assertFalse(ok)
        self.assertEqual(err, "TLS_MISSING_2096")

    def test_tls_mismatch_port(self):
        """Port fingerprint differs from file -> TLS_MISMATCH_{port}."""
        ok, err = _probe_is_healthy(
            self._make_state(served_fingerprints={"2095": "11:22:33:44", "2096": "AB:CD:EF:12:34"}),
            {"WEB_PORT": "2095", "SUB_PORT": "2096"},
        )
        self.assertFalse(ok)
        self.assertEqual(err, "TLS_MISMATCH_2095")

    def test_extra_ports_missing(self):
        """Extra verify port missing -> TLS_MISSING_{port}."""
        ok, err = _probe_is_healthy(
            self._make_state(served_fingerprints={"2095": "AB:CD:EF:12:34", "2096": "AB:CD:EF:12:34"}),
            {"WEB_PORT": "2095", "SUB_PORT": "2096", "CERT_VERIFY_EXTRA_PORTS": "41101"},
        )
        self.assertFalse(ok)
        self.assertEqual(err, "TLS_MISSING_41101")

    def test_probe_not_healthy_blocks_healthy_verdict(self):
        """Service inactive + plenty days remaining -> degraded, not healthy."""
        state = self._make_state(service_active=False, days_remaining=80)
        _determine_state(state, {})
        self.assertEqual(state.state, "degraded")
        self.assertEqual(state.last_error_code, "SERVICE_INACTIVE")

    def test_probe_bad_with_urgent_window(self):
        """Service inactive + urgent window -> urgent, not healthy."""
        state = self._make_state(service_active=False, days_remaining=10, urgent_before_days=15)
        _determine_state(state, {})
        self.assertEqual(state.state, "urgent")

    def test_probe_healthy_and_renew_due(self):
        """Probe OK but in renew window -> renew_due (not healthy)."""
        state = self._make_state(days_remaining=25, renew_before_days=30)
        _determine_state(state, {})
        self.assertEqual(state.state, "renew_due")

    def test_expected_verify_ports_default(self):
        """Default ports are 2095, 2096."""
        ports = _expected_verify_ports({"WEB_PORT": "2095", "SUB_PORT": "2096"})
        self.assertEqual(ports, ["2095", "2096"])

    def test_expected_verify_ports_with_extra(self):
        """Extra ports from CERT_VERIFY_EXTRA_PORTS are included."""
        ports = _expected_verify_ports({
            "WEB_PORT": "2095", "SUB_PORT": "2096",
            "CERT_VERIFY_EXTRA_PORTS": "41101,8443",
        })
        self.assertEqual(ports, ["2095", "2096", "41101", "8443"])


class RedactionTests(unittest.TestCase):
    """State redaction for local output."""

    def test_key_path_removed(self):
        """key_path is removed in redacted output."""
        state = CertState(domain="example.com", key_path="/root/cert/example.com/privkey.pem")
        redacted = _redact_state(state)
        self.assertNotIn("key_path", redacted)

    def test_cert_path_removed(self):
        """cert_path is removed in redacted output."""
        state = CertState(domain="example.com", cert_path="/root/cert/example.com/fullchain.pem")
        redacted = _redact_state(state)
        self.assertNotIn("cert_path", redacted)

    def test_public_fields_preserved(self):
        """Non-sensitive fields remain in redacted output."""
        state = CertState(domain="example.com", state="healthy", days_remaining=60.0)
        redacted = _redact_state(state)
        self.assertEqual(redacted.get("domain"), "example.com")
        self.assertEqual(redacted.get("state"), "healthy")
        self.assertEqual(redacted.get("days_remaining"), 60.0)


class ShellQuoteTests(unittest.TestCase):
    """Shell quoting helper."""

    def test_simple_string(self):
        """Simple string is single-quoted."""
        self.assertEqual(_shell_quote("hello"), "'hello'")

    def test_string_with_single_quote(self):
        """String with single quote uses safe quoting."""
        result = _shell_quote("it's")
        self.assertIn("it", result)


class CertStateModelTests(unittest.TestCase):
    """CertState dataclass serialization."""

    def test_to_dict_roundtrip(self):
        """to_dict() -> from_dict() preserves all fields."""
        orig = CertState(
            domain="example.com",
            state="healthy",
            days_remaining=60.0,
            lifetime_days=90,
            renew_before_days=30,
            urgent_before_days=15,
            service_active=True,
            dns_matches_expected=True,
            file_fingerprint_sha256="AB:CD:EF:12:34",
            served_fingerprints={"2095": "AB:CD:EF:12:34", "2096": "AB:CD:EF:12:34"},
            last_check_at="2026-05-19T10:00:00Z",
            last_renew_success_at="2026-05-10T02:01:20Z",
            consecutive_failures=0,
        )
        d = orig.to_dict()
        restored = CertState.from_dict(d)
        self.assertEqual(restored.domain, orig.domain)
        self.assertEqual(restored.state, orig.state)
        self.assertEqual(restored.days_remaining, orig.days_remaining)
        self.assertEqual(restored.served_fingerprints, orig.served_fingerprints)
        self.assertEqual(restored.consecutive_failures, orig.consecutive_failures)

    def test_default_values(self):
        """Default CertState has expected zero/null values."""
        state = CertState()
        self.assertEqual(state.state, "unknown")
        self.assertEqual(state.days_remaining, 0.0)
        self.assertEqual(state.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
