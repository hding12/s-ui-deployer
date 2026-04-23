import tempfile
import unittest
from pathlib import Path

from sui_deployer.config import ConfigError, load_env
from sui_deployer.validate import validate_site_config


class ConfigTests(unittest.TestCase):
    def test_load_env_supports_quoted_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "site.env"
            env_file.write_text('VPS_HOST="203.0.113.10"\nSSH_USER=ubuntu\n', encoding="utf-8")

            self.assertEqual(load_env(env_file), {"VPS_HOST": "203.0.113.10", "SSH_USER": "ubuntu"})

    def test_load_env_rejects_command_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "site.env"
            env_file.write_text('ROOT_PASSWORD="$(op read secret)"\n', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_env(env_file)

    def test_validate_rejects_source_config(self) -> None:
        result = validate_site_config(
            "s-ui-deployer/source/bad.env",
            {
                "VPS_HOST": "203.0.113.10",
                "SSH_USER": "ubuntu",
                "SSH_KEY_PATH": "../../shared/ssh-keys/aws-test.pem",
                "DOMAIN": "panel.example.org",
            },
        )

        self.assertTrue(any("source/" in error for error in result.errors))

    def test_validate_checks_tls_tag_binding(self) -> None:
        result = validate_site_config(
            "work/sites/example-site-1/site.env",
            {
                "VPS_HOST": "203.0.113.10",
                "SSH_USER": "ubuntu",
                "SSH_KEY_PATH": "../../shared/ssh-keys/aws-test.pem",
                "DOMAIN": "panel.example.org",
                "TLS_REALITY_TAG": "reality",
                "INBOUND_VLESS_TLS_TAG": "tls",
            },
        )

        self.assertTrue(any("INBOUND_VLESS_TLS_TAG" in error for error in result.errors))

    def test_validate_allows_direct_outbound_without_proxy_fields(self) -> None:
        result = validate_site_config(
            "work/sites/example-direct/site.env",
            {
                "VPS_HOST": "203.0.113.10",
                "SSH_USER": "ubuntu",
                "SSH_KEY_PATH": "../../shared/ssh-keys/aws-test.pem",
                "DOMAIN": "panel.example.org",
                "OUTBOUND_MODE": "direct",
            },
        )

        self.assertFalse(result.errors)

    def test_validate_requires_socks_server_and_port(self) -> None:
        result = validate_site_config(
            "work/sites/example-socks/site.env",
            {
                "VPS_HOST": "203.0.113.10",
                "SSH_USER": "ubuntu",
                "SSH_KEY_PATH": "../../shared/ssh-keys/aws-test.pem",
                "DOMAIN": "panel.example.org",
                "OUTBOUND_MODE": "socks",
            },
        )

        self.assertTrue(any("OUTBOUND_SERVER" in error for error in result.errors))
        self.assertTrue(any("OUTBOUND_PORT" in error for error in result.errors))

    def test_validate_rejects_unknown_outbound_mode(self) -> None:
        result = validate_site_config(
            "work/sites/example-bad/site.env",
            {
                "VPS_HOST": "203.0.113.10",
                "SSH_USER": "ubuntu",
                "SSH_KEY_PATH": "../../shared/ssh-keys/aws-test.pem",
                "DOMAIN": "panel.example.org",
                "OUTBOUND_MODE": "warp",
            },
        )

        self.assertTrue(any("OUTBOUND_MODE" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
