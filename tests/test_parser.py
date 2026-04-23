import unittest

from sui_deployer.parser import parse_initial_admin


class ParserTests(unittest.TestCase):
    def test_parse_initial_admin(self) -> None:
        output = """
        S-UI has been installed.
        username: admin-user
        password: strong-pass
        """

        self.assertEqual(parse_initial_admin(output), ("admin-user", "strong-pass"))

    def test_parse_initial_admin_returns_none_when_missing(self) -> None:
        self.assertEqual(parse_initial_admin("installation complete"), (None, None))

    def test_parse_initial_admin_strips_ansi_codes(self) -> None:
        output = "\x1b[0;32musername:LrudNHsm\x1b[0m\n\x1b[0;32mpassword:QYdKuJZr\x1b[0m"

        self.assertEqual(parse_initial_admin(output), ("LrudNHsm", "QYdKuJZr"))


if __name__ == "__main__":
    unittest.main()
