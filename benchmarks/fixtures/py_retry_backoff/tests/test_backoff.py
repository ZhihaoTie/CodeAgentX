import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backoff import retry_delays


class RetryDelaysTests(unittest.TestCase):
    def test_returns_one_delay_per_retry_attempt(self):
        self.assertEqual(retry_delays(3, base=0.5), [0.5, 1.0, 2.0])

    def test_caps_large_delays(self):
        self.assertEqual(retry_delays(5, base=10.0, cap=30.0), [10.0, 20.0, 30.0, 30.0, 30.0])

    def test_zero_attempts_returns_empty_list(self):
        self.assertEqual(retry_delays(0), [])


if __name__ == "__main__":
    unittest.main()
