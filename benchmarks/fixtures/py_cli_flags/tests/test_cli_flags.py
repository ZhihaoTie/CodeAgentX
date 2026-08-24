import unittest

from cli_flags import parse_flags


class ParseFlagsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(parse_flags([]), {"verbose": False, "limit": 10})

    def test_verbose_flag(self):
        self.assertEqual(parse_flags(["--verbose"]), {"verbose": True, "limit": 10})

    def test_limit_flag(self):
        self.assertEqual(parse_flags(["--limit", "5"]), {"verbose": False, "limit": 5})

    def test_combined_flags(self):
        self.assertEqual(
            parse_flags(["--verbose", "--limit", "3"]),
            {"verbose": True, "limit": 3},
        )


if __name__ == "__main__":
    unittest.main()
