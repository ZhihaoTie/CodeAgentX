import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.metrics import moving_average


class MovingAverageTests(unittest.TestCase):
    def test_computes_rolling_windows(self):
        self.assertEqual(moving_average([2, 4, 6, 8], 2), [3.0, 5.0, 7.0])

    def test_window_larger_than_values_returns_empty_list(self):
        self.assertEqual(moving_average([1, 2], 3), [])

    def test_rejects_non_positive_window(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()
