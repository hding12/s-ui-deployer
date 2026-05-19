"""Unit tests for chain data model and workflow helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sui_deployer.chain import (
    ChainConfig,
    ClientConfig,
    InboundConfig,
    OutboundConfig,
    chain_to_dict,
    delete_chain_file,
    dict_to_chain,
    list_chain_ids,
    load_chain,
    make_chain_id_from_name,
    save_chain,
    validate_chain_dict,
    validate_chain_id,
)
from sui_deployer.workflow.chain import (
    _add_route_rule,
    _build_client_payload,
    _build_inbound_payload,
    _build_outbound_payload,
    _check_create_conflicts,
    _client_password,
    _client_uuid,
    _detect_outbound_from_load,
    _extract_new_id,
    _find_by_name,
    _find_by_tag,
    _find_route_rule,
    _find_tls_id,
    _outbound_has_other_references,
    _redact_chain,
    _remove_route_rule,
    _resolve_tls_tag,
    _update_chain_data_with_generated,
    _verify_chain_created,
    _verify_chain_deleted,
)


class ChainDataModelTests(unittest.TestCase):
    """Tests for chain.py data model and file I/O."""

    # ── Dataclass roundtrip ──

    def test_dict_to_chain_roundtrip(self) -> None:
        raw = {
            "chain_id": "alice-phone",
            "name": "alice-phone",
            "client": {
                "uuid": "abc-123",
                "password": "secret-pass",
                "volume": 0,
                "expiry": 0,
            },
            "inbound": {
                "type": "vless",
                "tag": "vless-alice-phone",
                "listen_port": 11001,
                "tls_tag": "reality",
                "transport": {},
                "addrs": [],
            },
            "outbound": {
                "mode": "dedicated",
                "tag": "socks-alice-phone",
                "type": "socks",
                "server": "res-proxy.example.com",
                "server_port": 1080,
                "username": "proxy-user",
                "password": "proxy-pass",
            },
            "metadata": {"source": "test"},
        }
        chain = dict_to_chain(raw)
        self.assertIsInstance(chain, ChainConfig)
        self.assertEqual(chain.chain_id, "alice-phone")
        self.assertEqual(chain.name, "alice-phone")
        self.assertEqual(chain.client.uuid, "abc-123")
        self.assertEqual(chain.inbound.type, "vless")
        self.assertEqual(chain.inbound.listen_port, 11001)
        self.assertEqual(chain.outbound.mode, "dedicated")
        self.assertEqual(chain.outbound.server, "res-proxy.example.com")

        back = chain_to_dict(chain)
        self.assertEqual(back["chain_id"], "alice-phone")
        self.assertEqual(back["inbound"]["listen_port"], 11001)
        self.assertEqual(back["outbound"]["mode"], "dedicated")
        self.assertEqual(back["metadata"]["source"], "test")

    # ── validate_chain_id ──

    def test_validate_chain_id_valid(self) -> None:
        self.assertEqual(validate_chain_id("alice-phone"), [])
        self.assertEqual(validate_chain_id("chain_1"), [])
        self.assertEqual(validate_chain_id("a"), [])
        self.assertEqual(validate_chain_id("test.chain-01"), [])

    def test_validate_chain_id_invalid(self) -> None:
        errors = validate_chain_id("")
        self.assertTrue(any("empty" in e for e in errors))

        errors = validate_chain_id("1234567890.1234567890.1234567890.1234567890.1234567890.1234567890.xxx")
        self.assertTrue(any("64" in e for e in errors))

        errors = validate_chain_id("-starts-with-dash")
        self.assertTrue(any("start" in e.lower() for e in errors))

        errors = validate_chain_id(".starts-with-dot")
        self.assertTrue(any("start" in e.lower() for e in errors))

    # ── validate_chain_dict ──

    def test_validate_chain_dict_direct_mode(self) -> None:
        data = {
            "chain_id": "test-chain",
            "name": "test-chain",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "direct"},
        }
        errors = validate_chain_dict(data)
        self.assertEqual(errors, [])

    def test_validate_chain_dict_shared_mode(self) -> None:
        data = {
            "chain_id": "test-chain",
            "name": "test-chain",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "shared", "tag": "socks-residential"},
        }
        errors = validate_chain_dict(data)
        self.assertEqual(errors, [])

    def test_validate_chain_dict_dedicated_mode(self) -> None:
        data = {
            "chain_id": "test-chain",
            "name": "test-chain",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {
                "mode": "dedicated",
                "tag": "socks-test",
                "server": "proxy.example.com",
                "server_port": 1080,
            },
        }
        errors = validate_chain_dict(data)
        self.assertEqual(errors, [])

    def test_validate_chain_dict_missing_name(self) -> None:
        data = {
            "chain_id": "test",
            "name": "",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "direct"},
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("name" in e for e in errors))

    def test_validate_chain_dict_invalid_outbound_mode(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "unknown"},
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("mode" in e and "direct" in e for e in errors))

    def test_validate_chain_dict_dedicated_missing_server(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {
                "mode": "dedicated",
                "tag": "socks-test",
                "server": "",
                "server_port": 0,
            },
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("server" in e for e in errors))

    def test_validate_chain_dict_shared_missing_tag(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "shared", "tag": ""},
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("tag" in e for e in errors))

    def test_validate_chain_dict_missing_tls_tag(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "",
            },
            "outbound": {"mode": "direct"},
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("tls_tag" in e for e in errors))

    def test_validate_chain_dict_invalid_port(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 99999,
                "tls_tag": "reality",
            },
            "outbound": {"mode": "direct"},
        }
        errors = validate_chain_dict(data)
        self.assertTrue(any("port" in e for e in errors))

    # ── make_chain_id_from_name ──

    def test_make_chain_id_from_name(self) -> None:
        self.assertEqual(make_chain_id_from_name("alice-phone"), "alice-phone")
        self.assertEqual(make_chain_id_from_name("Alice Phone!"), "Alice-Phone")
        self.assertEqual(make_chain_id_from_name("   "), "chain-")

    # ── File I/O ──

    def test_file_io_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            # Write a dummy site.env so chains_dir resolves to the parent
            Path(config_path).touch()

            chain_data = {
                "chain_id": "test-chain",
                "name": "test-chain",
                "inbound": {
                    "type": "vless",
                    "tag": "vless-test",
                    "listen_port": 11001,
                    "tls_tag": "reality",
                },
                "outbound": {"mode": "direct"},
            }

            saved = save_chain(config_path, "test-chain", chain_data)
            self.assertTrue(saved.exists())
            self.assertEqual(saved.name, "test-chain.json")

            loaded = load_chain(config_path, "test-chain")
            self.assertEqual(loaded["chain_id"], "test-chain")
            self.assertEqual(loaded["inbound"]["listen_port"], 11001)

            ids = list_chain_ids(config_path)
            self.assertIn("test-chain", ids)

            deleted = delete_chain_file(config_path, "test-chain")
            self.assertTrue(deleted)

            ids_after = list_chain_ids(config_path)
            self.assertNotIn("test-chain", ids_after)

    def test_chain_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            with self.assertRaises(FileNotFoundError):
                load_chain(config_path, "nonexistent")

    def test_list_empty_chains_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            self.assertEqual(list_chain_ids(config_path), [])


class FakeApi:
    """Mock SuiApiV2 that records saved config for testing."""

    def __init__(self) -> None:
        self.saved_config: dict | None = None

    def get(self, path: str) -> dict:
        return {"success": True, "obj": {}}

    def post(self, path: str, data: dict[str, str]) -> dict:
        if path == "apiv2/save":
            obj = data.get("object")
            if obj == "config":
                data_json = data.get("data", "{}")
                self.saved_config = json.loads(data_json)
        return {"success": True, "obj": {}}


class ChainWorkflowHelperTests(unittest.TestCase):
    """Tests for workflow/chain.py helper functions."""

    # ── _find_by_tag / _find_by_name ──

    def test_find_by_tag_found(self) -> None:
        items = [{"tag": "vless-reality", "id": 1}, {"tag": "trojan-ws", "id": 2}]
        result = _find_by_tag(items, "vless-reality")
        self.assertEqual(result, {"tag": "vless-reality", "id": 1})

    def test_find_by_tag_not_found(self) -> None:
        result = _find_by_tag([], "nonexistent")
        self.assertIsNone(result)

    def test_find_by_name_found(self) -> None:
        items = [{"name": "client-1", "id": 1}, {"name": "client-2", "id": 2}]
        result = _find_by_name(items, "client-1")
        self.assertEqual(result, {"name": "client-1", "id": 1})

    # ── _find_tls_id ──

    def test_find_tls_id_found(self) -> None:
        load = {"tls": [{"id": 5, "name": "reality"}, {"id": 6, "name": "tls"}]}
        self.assertEqual(_find_tls_id(load, "reality"), 5)
        self.assertEqual(_find_tls_id(load, "tls"), 6)

    def test_find_tls_id_not_found(self) -> None:
        load = {"tls": []}
        self.assertIsNone(_find_tls_id(load, "reality"))

    # ── _resolve_tls_tag ──

    def test_resolve_tls_tag_found(self) -> None:
        inbound = {"tls_id": 5}
        load = {"tls": [{"id": 5, "name": "reality"}, {"id": 6, "name": "tls"}]}
        self.assertEqual(_resolve_tls_tag(inbound, load), "reality")

    def test_resolve_tls_tag_not_found(self) -> None:
        inbound = {"tls_id": 99}
        load = {"tls": [{"id": 5, "name": "reality"}]}
        self.assertEqual(_resolve_tls_tag(inbound, load), "")

    def test_resolve_tls_tag_no_id(self) -> None:
        inbound = {}
        load = {"tls": [{"id": 5, "name": "reality"}]}
        self.assertEqual(_resolve_tls_tag(inbound, load), "")

    # ── _detect_outbound_from_load ──

    def test_detect_outbound_direct(self) -> None:
        mode, tag, data = _detect_outbound_from_load("direct", [])
        self.assertEqual(mode, "direct")
        self.assertEqual(tag, "")
        self.assertEqual(data, {})

    def test_detect_outbound_direct_empty(self) -> None:
        mode, tag, data = _detect_outbound_from_load("", [])
        self.assertEqual(mode, "direct")
        self.assertEqual(tag, "")

    def test_detect_outbound_shared(self) -> None:
        outbounds = [{"tag": "socks-residential", "server": "proxy.example.com", "server_port": 1080}]
        mode, tag, data = _detect_outbound_from_load("socks-residential", outbounds)
        self.assertEqual(mode, "shared")
        self.assertEqual(tag, "socks-residential")
        self.assertEqual(data["server"], "proxy.example.com")

    def test_detect_outbound_shared_not_found(self) -> None:
        mode, tag, data = _detect_outbound_from_load("some-tag", [])
        self.assertEqual(mode, "shared")
        self.assertEqual(tag, "some-tag")
        self.assertEqual(data, {})

    # ── _client_uuid / _client_password ──

    def test_client_uuid_from_vless(self) -> None:
        client = {"config": {"vless": {"uuid": "abc-123"}}}
        self.assertEqual(_client_uuid(client), "abc-123")

    def test_client_uuid_from_tuic(self) -> None:
        client = {"config": {"tuic": {"uuid": "def-456"}}}
        self.assertEqual(_client_uuid(client), "def-456")

    def test_client_uuid_empty(self) -> None:
        self.assertEqual(_client_uuid({}), "")
        self.assertEqual(_client_uuid({"config": {}}), "")

    def test_client_password_from_tuic(self) -> None:
        client = {"config": {"tuic": {"password": "pw-123"}}}
        self.assertEqual(_client_password(client), "pw-123")

    def test_client_password_from_hysteria2(self) -> None:
        client = {"config": {"hysteria2": {"password": "hy-pw"}}}
        self.assertEqual(_client_password(client), "hy-pw")

    def test_client_password_empty(self) -> None:
        self.assertEqual(_client_password({}), "")

    # ── _build_outbound_payload ──

    def test_build_outbound_payload(self) -> None:
        chain_data = {
            "outbound": {
                "mode": "dedicated",
                "tag": "socks-test",
                "type": "socks",
                "server": "proxy.example.com",
                "server_port": 1080,
                "username": "user1",
                "password": "pass1",
            }
        }
        payload = _build_outbound_payload(chain_data)
        self.assertEqual(payload["tag"], "socks-test")
        self.assertEqual(payload["server"], "proxy.example.com")
        self.assertEqual(payload["server_port"], 1080)
        self.assertEqual(payload["username"], "user1")
        self.assertEqual(payload["password"], "pass1")
        self.assertEqual(payload["version"], "5")

    # ── _build_inbound_payload ──

    def test_build_inbound_payload(self) -> None:
        chain_data = {
            "inbound": {
                "type": "vless",
                "tag": "vless-test",
                "listen_port": 11001,
                "tls_tag": "reality",
                "transport": {},
                "addrs": [],
            }
        }
        payload = _build_inbound_payload(chain_data, tls_id=5)
        self.assertEqual(payload["type"], "vless")
        self.assertEqual(payload["tag"], "vless-test")
        self.assertEqual(payload["listen_port"], 11001)
        self.assertEqual(payload["tls_id"], 5)
        self.assertEqual(payload["listen"], "::")

    # ── _build_client_payload ──

    def test_build_client_payload_vless(self) -> None:
        chain_data = {"name": "alice", "client": {"uuid": "", "password": "", "volume": 0, "expiry": 0}}
        payload = _build_client_payload(chain_data, "vless", inbound_id=10)
        self.assertEqual(payload["name"], "alice")
        self.assertIn("vless", payload["config"])
        self.assertEqual(payload["config"]["vless"]["flow"], "xtls-rprx-vision")
        self.assertIn("uuid", payload["config"]["vless"])
        self.assertEqual(payload["inbounds"], [10])

    def test_build_client_payload_trojan(self) -> None:
        chain_data = {"name": "bob", "client": {"uuid": "", "password": "bob-pass", "volume": 0, "expiry": 0}}
        payload = _build_client_payload(chain_data, "trojan", inbound_id=11)
        self.assertEqual(payload["name"], "bob")
        self.assertIn("trojan", payload["config"])
        self.assertEqual(payload["config"]["trojan"]["password"], "bob-pass")
        self.assertEqual(payload["inbounds"], [11])

    def test_build_client_payload_with_uuid(self) -> None:
        chain_data = {"name": "carol", "client": {"uuid": "fixed-uuid-123", "password": "", "volume": 0, "expiry": 0}}
        payload = _build_client_payload(chain_data, "vless", inbound_id=12)
        self.assertEqual(payload["config"]["vless"]["uuid"], "fixed-uuid-123")

    # ── _extract_new_id ──

    def test_extract_new_id_found(self) -> None:
        response = {
            "success": True,
            "obj": {
                "inbounds": [
                    {"id": 1, "tag": "existing"},
                    {"id": 2, "tag": "new-inbound"},
                ]
            },
        }
        result = _extract_new_id(response, "inbounds", "tag", "new-inbound")
        self.assertEqual(result, 2)

    def test_extract_new_id_not_found(self) -> None:
        response = {"success": True, "obj": {"inbounds": []}}
        result = _extract_new_id(response, "inbounds", "tag", "nonexistent")
        self.assertIsNone(result)

    # ── _check_create_conflicts ──

    def test_check_create_conflicts_no_issues(self) -> None:
        chain_data = {
            "name": "new-client",
            "inbound": {"type": "vless", "tag": "new-inbound", "listen_port": 22001, "tls_tag": "reality"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [],
            "outbounds": [],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_check_create_conflicts_tag_conflict(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"type": "vless", "tag": "existing-tag", "listen_port": 11001, "tls_tag": "reality"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [{"tag": "existing-tag", "listen_port": 9999}],
            "outbounds": [],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertEqual(errors, [])
        self.assertTrue(any("tag" in i and "已存在" in i for i in warnings))

    def test_check_create_conflicts_port_conflict(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"type": "vless", "tag": "new-inbound", "listen_port": 443, "tls_tag": "reality"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [{"tag": "other-inbound", "listen_port": 443}],
            "outbounds": [],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertTrue(any("端口" in i and "443" in i for i in errors))
        self.assertEqual(warnings, [])

    def test_check_create_conflicts_tls_missing(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"type": "vless", "tag": "new-inbound", "listen_port": 11001, "tls_tag": "nonexistent"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [],
            "outbounds": [],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertTrue(any("TLS 模板" in i and "nonexistent" in i for i in errors))
        self.assertEqual(warnings, [])

    def test_check_create_conflicts_shared_outbound_missing(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"type": "vless", "tag": "new-inbound", "listen_port": 11001, "tls_tag": "reality"},
            "outbound": {"mode": "shared", "tag": "missing-out"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [],
            "outbounds": [{"tag": "existing-out"}],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertTrue(any("不存在" in i and "missing-out" in i for i in errors))
        self.assertEqual(warnings, [])

    def test_check_create_conflicts_shared_outbound_ok(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"type": "vless", "tag": "new-inbound", "listen_port": 11001, "tls_tag": "reality"},
            "outbound": {"mode": "shared", "tag": "existing-out"},
        }
        load = {
            "tls": [{"id": 1, "name": "reality"}],
            "inbounds": [],
            "outbounds": [{"tag": "existing-out"}],
            "clients": [],
        }
        errors, warnings = _check_create_conflicts(chain_data, load)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    # ── _redact_chain ──

    def test_redact_chain_hides_sensitive(self) -> None:
        data = {
            "chain_id": "test",
            "name": "test",
            "client": {"uuid": "secret-uuid", "password": "secret-pass"},
            "inbound": {"type": "vless", "tag": "inbound-tag"},
            "outbound": {"mode": "dedicated", "server": "proxy.example.com", "username": "admin", "password": "admin-pass"},
        }
        redacted = _redact_chain(data)
        self.assertEqual(redacted["client"]["uuid"], "***REDACTED***")
        self.assertEqual(redacted["client"]["password"], "***REDACTED***")
        self.assertEqual(redacted["inbound"]["tag"], "inbound-tag")
        self.assertEqual(redacted["inbound"]["type"], "vless")
        # server address is not a sensitive key; password/username are
        self.assertEqual(redacted["outbound"]["password"], "***REDACTED***")
        self.assertEqual(redacted["outbound"]["username"], "***REDACTED***")
        self.assertEqual(redacted["chain_id"], "test")

    def test_redact_chain_preserves_empty(self) -> None:
        data = {"client": {"uuid": "", "password": ""}}
        redacted = _redact_chain(data)
        self.assertEqual(redacted["client"]["uuid"], "")
        self.assertEqual(redacted["client"]["password"], "")

    # ── Route rule management ──

    def _make_fake_api(self) -> FakeApi:
        return FakeApi()

    def test_add_route_rule_adds_rule(self) -> None:
        load = {"config": {"route": {"rules": [], "final": "direct"}}}
        api = self._make_fake_api()
        _add_route_rule(api, load, "inbound-a", "outbound-b")
        saved_config = api.saved_config
        self.assertIsNotNone(saved_config)
        rules = saved_config["route"]["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["inbound"], ["inbound-a"])
        self.assertEqual(rules[0]["outbound"], "outbound-b")
        # route.final is preserved
        self.assertEqual(saved_config["route"]["final"], "direct")

    def test_add_route_rule_idempotent_same_inbound(self) -> None:
        load = {
            "config": {
                "route": {
                    "rules": [{"inbound": ["inbound-a"], "outbound": "old-outbound"}],
                    "final": "direct",
                }
            }
        }
        api = self._make_fake_api()
        _add_route_rule(api, load, "inbound-a", "new-outbound")
        rules = api.saved_config["route"]["rules"]
        # Should be exactly 1 rule for inbound-a (replaced, not duplicated)
        matching = [r for r in rules if r.get("inbound") == ["inbound-a"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["outbound"], "new-outbound")

    def test_remove_route_rule_removes_matching(self) -> None:
        load = {
            "config": {
                "route": {
                    "rules": [
                        {"inbound": ["inbound-a"], "outbound": "out-a"},
                        {"inbound": ["inbound-b"], "outbound": "out-b"},
                    ],
                    "final": "direct",
                }
            }
        }
        api = self._make_fake_api()
        _remove_route_rule(api, load, "inbound-a")
        rules = api.saved_config["route"]["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["inbound"], ["inbound-b"])

    def test_remove_route_rule_no_match_does_nothing(self) -> None:
        load = {
            "config": {
                "route": {
                    "rules": [{"inbound": ["inbound-a"], "outbound": "out-a"}],
                    "final": "direct",
                }
            }
        }
        api = self._make_fake_api()
        _remove_route_rule(api, load, "nonexistent")
        # Should not have called save
        self.assertIsNone(api.saved_config)

    # ── _find_route_rule ──

    def test_find_route_rule_found(self) -> None:
        rules = [
            {"inbound": ["inbound-a"], "outbound": "out-a"},
            {"inbound": ["inbound-b"], "outbound": "out-b"},
        ]
        self.assertEqual(_find_route_rule(rules, "inbound-a")["outbound"], "out-a")

    def test_find_route_rule_not_found(self) -> None:
        self.assertIsNone(_find_route_rule([], "nonexistent"))

    def test_find_route_rule_empty_inbound_list(self) -> None:
        rules = [{"inbound": [], "outbound": "out-a"}]
        self.assertIsNone(_find_route_rule(rules, "inbound-a"))

    # ── _outbound_has_other_references with exclude_chain_id ──

    def test_outbound_has_other_references_excludes_self(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            chain_dir = Path(config_path).parent / "chains"
            chain_dir.mkdir()
            # Create a single chain file that references the outbound
            (chain_dir / "self.json").write_text(
                json.dumps({
                    "chain_id": "self",
                    "outbound": {"mode": "dedicated", "tag": "socks-test"},
                }),
                encoding="utf-8",
            )
            # Without exclude_chain_id it finds it
            self.assertTrue(_outbound_has_other_references(config_path, "socks-test"))
            # With exclude_chain_id=self it doesn't find it
            self.assertFalse(_outbound_has_other_references(config_path, "socks-test", exclude_chain_id="self"))

    # ── _verify_chain_deleted strict checks ──

    def test_verify_chain_deleted_detects_stale_inbound_id(self) -> None:
        chain_data = {
            "name": "test",
            "chain_id": "test-chain",
            "inbound": {"tag": "in-deleted"},
            "outbound": {"mode": "direct"},
            "metadata": {"inbound_id": 42},
        }
        load = {
            "clients": [{"name": "test", "inbounds": [42]}],
            "inbounds": [],  # inbound 42 was deleted, but client still references it
            "config": {"route": {"rules": [], "final": "direct"}},
        }
        # Should detect stale inbound ID 42 in client's inbounds list
        self.assertFalse(_verify_chain_deleted(chain_data, load, inbound_id=42))

    def test_verify_chain_deleted_dedicated_outbound_leftover(self) -> None:
        chain_data = {
            "name": "test",
            "chain_id": "test-chain",
            "inbound": {"tag": "in-gone"},
            "outbound": {"mode": "dedicated", "tag": "out-leftover"},
        }
        load = {
            "clients": [],
            "inbounds": [],
            "outbounds": [{"tag": "out-leftover"}],
            "config": {"route": {"rules": [], "final": "direct"}},
        }
        # Without config_path (can't check refs), leftover should fail
        self.assertFalse(_verify_chain_deleted(chain_data, load))

    def test_verify_chain_deleted_dedicated_outbound_other_ref(self) -> None:
        chain_data = {
            "name": "test",
            "chain_id": "test-chain",
            "inbound": {"tag": "in-gone"},
            "outbound": {"mode": "dedicated", "tag": "out-shared"},
        }
        load = {
            "clients": [],
            "inbounds": [],
            "outbounds": [{"tag": "out-shared"}],
            "config": {"route": {"rules": [], "final": "direct"}},
        }
        # With config_path where another chain references the outbound, keep is OK
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            chain_dir = Path(config_path).parent / "chains"
            chain_dir.mkdir()
            (chain_dir / "other.json").write_text(
                json.dumps({
                    "chain_id": "other",
                    "outbound": {"mode": "shared", "tag": "out-shared"},
                }),
                encoding="utf-8",
            )
            self.assertTrue(_verify_chain_deleted(chain_data, load, config_path))

    # ── _update_chain_data_with_generated generic fallback ──

    def test_update_chain_data_with_generated_generic_fallback(self) -> None:
        chain_data = {"name": "test", "client": {"uuid": "", "password": ""}}
        client_payload = {
            "config": {
                "custom-proto": {
                    "name": "test",
                    "password": "generic-pass-gen",
                }
            }
        }
        _update_chain_data_with_generated(chain_data, client_payload)
        self.assertEqual(chain_data["client"]["password"], "generic-pass-gen")

    # ── Verify functions return bool ──

    def test_verify_chain_created_all_found(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"tag": "in-test", "type": "vless"},
            "outbound": {"mode": "dedicated", "tag": "out-test"},
        }
        load = {
            "clients": [{"name": "test"}],
            "inbounds": [{"tag": "in-test"}],
            "outbounds": [{"tag": "out-test"}],
            "config": {
                "route": {
                    "rules": [{"inbound": ["in-test"], "outbound": "out-test"}],
                    "final": "direct",
                }
            },
        }
        self.assertTrue(_verify_chain_created(chain_data, load))

    def test_verify_chain_created_missing_inbound(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"tag": "in-missing", "type": "vless"},
            "outbound": {"mode": "direct"},
        }
        load = {"clients": [{"name": "test"}], "inbounds": [], "config": {"route": {}}}
        self.assertFalse(_verify_chain_created(chain_data, load))

    def test_verify_chain_created_shared_outbound_missing(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"tag": "in-test", "type": "vless"},
            "outbound": {"mode": "shared", "tag": "missing-out"},
        }
        load = {
            "clients": [{"name": "test"}],
            "inbounds": [{"tag": "in-test"}],
            "outbounds": [],  # missing-out not here
            "config": {
                "route": {
                    "rules": [{"inbound": ["in-test"], "outbound": "missing-out"}],
                    "final": "direct",
                }
            },
        }
        self.assertFalse(_verify_chain_created(chain_data, load))

    def test_verify_chain_deleted_all_removed(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"tag": "in-gone"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "clients": [],
            "inbounds": [],
            "config": {"route": {"rules": [], "final": "direct"}},
        }
        self.assertTrue(_verify_chain_deleted(chain_data, load))

    def test_verify_chain_deleted_inbound_still_exists(self) -> None:
        chain_data = {
            "name": "test",
            "inbound": {"tag": "in-still-here"},
            "outbound": {"mode": "direct"},
        }
        load = {
            "clients": [],
            "inbounds": [{"tag": "in-still-here"}],
            "config": {"route": {"rules": [], "final": "direct"}},
        }
        self.assertFalse(_verify_chain_deleted(chain_data, load))

    # ── _outbound_has_other_references ──

    def test_outbound_has_other_references_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            # Create a chain file that references this outbound
            chain_dir = Path(config_path).parent / "chains"
            chain_dir.mkdir()
            (chain_dir / "other.json").write_text(
                json.dumps({"outbound": {"mode": "shared", "tag": "socks-test"}}),
                encoding="utf-8",
            )
            self.assertTrue(_outbound_has_other_references(config_path, "socks-test"))

    def test_outbound_has_other_references_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = str(Path(tmpdir) / "site.env")
            Path(config_path).touch()
            self.assertFalse(_outbound_has_other_references(config_path, "socks-test"))

    # ── _update_chain_data_with_generated ──

    def test_update_chain_data_with_generated_vless(self) -> None:
        chain_data = {"name": "test", "client": {"uuid": "", "password": ""}}
        client_payload = {
            "config": {
                "vless": {
                    "name": "test",
                    "uuid": "generated-uuid-123",
                    "flow": "xtls-rprx-vision",
                }
            }
        }
        _update_chain_data_with_generated(chain_data, client_payload)
        self.assertEqual(chain_data["client"]["uuid"], "generated-uuid-123")

    def test_update_chain_data_with_generated_trojan(self) -> None:
        chain_data = {"name": "test", "client": {"uuid": "", "password": ""}}
        client_payload = {
            "config": {
                "trojan": {
                    "name": "test",
                    "password": "trojan-pass-gen",
                }
            }
        }
        _update_chain_data_with_generated(chain_data, client_payload)
        self.assertEqual(chain_data["client"]["password"], "trojan-pass-gen")

    def test_update_chain_data_with_generated_prefers_existing(self) -> None:
        chain_data = {"name": "test", "client": {"uuid": "existing-uuid", "password": "existing-pass"}}
        client_payload = {
            "config": {
                "vless": {
                    "name": "test",
                    "uuid": "existing-uuid",
                    "flow": "xtls-rprx-vision",
                }
            }
        }
        _update_chain_data_with_generated(chain_data, client_payload)
        self.assertEqual(chain_data["client"]["uuid"], "existing-uuid")
        self.assertEqual(chain_data["client"]["password"], "existing-pass")


if __name__ == "__main__":
    unittest.main()
