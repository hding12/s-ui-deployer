import unittest

from sui_deployer.workflow.apply import (
    _build_plan,
    _client_name,
    _full_client,
    _keypair_value,
    outbound_mode_from_config,
    redact,
)


class FakeApi:
    def get(self, path: str):
        self.path = path
        return {
            "success": True,
            "obj": {
                "clients": [
                    {
                        "id": 9,
                        "name": "primary-client",
                        "config": {"vless": {"uuid": "full-client-uuid"}},
                        "inbounds": [4],
                    }
                ]
            },
        }


class ApplyWorkflowTests(unittest.TestCase):
    def test_keypair_value_strips_label_prefix(self) -> None:
        self.assertEqual(_keypair_value("PrivateKey: abc123", "PrivateKey"), "abc123")
        self.assertEqual(_keypair_value("PublicKey: def456", "PublicKey"), "def456")

    def test_redact_hides_runtime_credentials(self) -> None:
        redacted = redact(
            {
                "username": "proxy-user",
                "password": "proxy-pass",
                "transport": {"path": "/secret-ws-path"},
                "tag": "trojan-ws",
            }
        )

        self.assertEqual(redacted["username"], "***REDACTED***")
        self.assertEqual(redacted["password"], "***REDACTED***")
        self.assertEqual(redacted["transport"]["path"], "***REDACTED***")
        self.assertEqual(redacted["tag"], "trojan-ws")

    def test_build_plan_keeps_existing_client_credentials_and_mounts_all_inbounds(self) -> None:
        values = {
            "DOMAIN": "panel.example.org",
            "SSL_CERT_FULLCHAIN_PATH": "/root/cert/panel.example.org/fullchain.pem",
            "SSL_CERT_KEY_PATH": "/root/cert/panel.example.org/privkey.pem",
            "OUTBOUND_SERVER": "198.51.100.10",
            "OUTBOUND_PORT": "1080",
            "OUTBOUND_USERNAME": "proxy-user",
            "OUTBOUND_PASSWORD": "proxy-pass",
            "SITE_ID": "example-site",
            "CLIENT_NAME": "primary-client",
        }
        load = {
            "config": {"route": {"rules": []}},
            "tls": [
                {"id": 1, "name": "reality"},
                {"id": 2, "name": "tls"},
                {"id": 3, "name": "hy2-tls"},
            ],
            "outbounds": [],
            "inbounds": [
                {"id": 1, "tag": "vless-reality"},
                {"id": 2, "tag": "tuic-59501"},
                {"id": 3, "tag": "hysteria2"},
                {"id": 4, "tag": "trojan-ws"},
            ],
            "clients": [
                {
                    "id": 9,
                    "name": "primary-client",
                    "config": {"vless": {"uuid": "keep-this-uuid"}},
                    "inbounds": [4],
                    "links": [],
                }
            ],
        }

        plan = _build_plan(values, load, api=None)
        client_ops = [op for op in plan["operations"] if op["object"] == "clients"]

        self.assertEqual(len(client_ops), 1)
        self.assertEqual(client_ops[0]["action"], "edit")
        self.assertEqual(client_ops[0]["data"]["name"], "example-site")
        self.assertEqual(client_ops[0]["data"]["config"]["vless"]["name"], "example-site")
        self.assertEqual(client_ops[0]["data"]["config"]["vless"]["uuid"], "keep-this-uuid")
        self.assertEqual(client_ops[0]["data"]["inbounds"], [1, 2, 3, 4])

    def test_client_name_prefers_site_id(self) -> None:
        self.assertEqual(_client_name({"SITE_ID": "example-site", "CLIENT_NAME": "primary-client"}), "example-site")
        self.assertEqual(_client_name({"CLIENT_NAME": "primary-client"}), "primary-client")

    def test_full_client_fetches_config_when_load_omits_it(self) -> None:
        api = FakeApi()
        client = _full_client({"id": 9, "name": "primary-client", "inbounds": [4]}, api)  # type: ignore[arg-type]

        self.assertEqual(api.path, "apiv2/clients?id=9")
        self.assertEqual(client["config"]["vless"]["uuid"], "full-client-uuid")

    def test_build_plan_direct_mode_skips_socks_outbound_and_uses_direct_final(self) -> None:
        values = self._base_values()
        values["OUTBOUND_MODE"] = "direct"
        plan = _build_plan(values, self._base_load(), api=None)

        self.assertFalse(any(op["object"] == "outbounds" for op in plan["operations"]))
        config_op = next(op for op in plan["operations"] if op["object"] == "config")
        self.assertEqual(config_op["data"]["route"]["final"], "direct")

    def test_build_plan_socks_mode_keeps_socks_outbound(self) -> None:
        values = self._base_values()
        values["OUTBOUND_MODE"] = "socks"
        plan = _build_plan(values, self._base_load(), api=None)

        outbound_op = next(op for op in plan["operations"] if op["object"] == "outbounds")
        self.assertEqual(outbound_op["data"]["type"], "socks")
        config_op = next(op for op in plan["operations"] if op["object"] == "config")
        self.assertEqual(config_op["data"]["route"]["final"], "socks-residential")

    def test_outbound_mode_auto_detects_direct_or_socks(self) -> None:
        self.assertEqual(outbound_mode_from_config({}), "direct")
        self.assertEqual(outbound_mode_from_config({"OUTBOUND_SERVER": "198.51.100.10", "OUTBOUND_PORT": "1080"}), "socks")
        self.assertEqual(outbound_mode_from_config({"OUTBOUND_MODE": "direct"}), "direct")

    def _base_values(self) -> dict[str, str]:
        return {
            "DOMAIN": "panel.example.org",
            "SSL_CERT_FULLCHAIN_PATH": "/root/cert/panel.example.org/fullchain.pem",
            "SSL_CERT_KEY_PATH": "/root/cert/panel.example.org/privkey.pem",
            "OUTBOUND_TAG": "socks-residential",
            "OUTBOUND_SERVER": "198.51.100.10",
            "OUTBOUND_PORT": "1080",
            "OUTBOUND_USERNAME": "proxy-user",
            "OUTBOUND_PASSWORD": "proxy-pass",
            "SITE_ID": "example-site",
        }

    def _base_load(self) -> dict:
        return {
            "config": {"route": {"rules": []}},
            "tls": [
                {"id": 1, "name": "reality"},
                {"id": 2, "name": "tls"},
                {"id": 3, "name": "hy2-tls"},
            ],
            "outbounds": [{"id": 1, "type": "direct", "tag": "direct"}],
            "inbounds": [
                {"id": 1, "tag": "vless-reality"},
                {"id": 2, "tag": "tuic-59501"},
                {"id": 3, "tag": "hysteria2"},
                {"id": 4, "tag": "trojan-ws"},
            ],
            "clients": [],
        }


if __name__ == "__main__":
    unittest.main()
