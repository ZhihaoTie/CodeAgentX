import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.service import status_label


class ServiceStatusTests(unittest.TestCase):
    def test_enabled_label(self):
        self.assertEqual(status_label(True), "enabled")

    def test_disabled_label(self):
        self.assertEqual(status_label(False), "disabled")


if __name__ == "__main__":
    unittest.main()
