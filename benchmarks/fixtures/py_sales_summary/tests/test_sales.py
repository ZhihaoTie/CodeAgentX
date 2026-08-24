import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sales import summarize_sales


class SummarizeSalesTests(unittest.TestCase):
    def test_ignores_refunded_sales(self):
        rows = [
            {"amount": 10.0, "status": "paid"},
            {"amount": 5.0, "status": "refunded"},
            {"amount": 20.0, "status": "paid"},
        ]

        self.assertEqual(summarize_sales(rows), {"count": 2, "total": 30.0, "average": 15.0})

    def test_empty_paid_sales_have_zero_average(self):
        self.assertEqual(summarize_sales([{"amount": 5.0, "status": "refunded"}]), {"count": 0, "total": 0.0, "average": 0.0})


if __name__ == "__main__":
    unittest.main()
