import unittest

from sui_deployer.render import redact_config


class RenderTests(unittest.TestCase):
    def test_redact_config_hides_sensitive_values(self) -> None:
        redacted = redact_config(
            {
                "DOMAIN": "panel.example.org",
                "ROOT_PASSWORD": "secret",
                "TLS_REALITY_PRIVATE_KEY": "private",
                "SUI_API_TOKEN": "token",
            }
        )

        self.assertEqual(redacted["DOMAIN"], "panel.example.org")
        self.assertEqual(redacted["ROOT_PASSWORD"], "***REDACTED***")
        self.assertEqual(redacted["TLS_REALITY_PRIVATE_KEY"], "***REDACTED***")
        self.assertEqual(redacted["SUI_API_TOKEN"], "***REDACTED***")


if __name__ == "__main__":
    unittest.main()
