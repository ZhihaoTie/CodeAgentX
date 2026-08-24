import unittest

from calculator import add, multiply


class CalculatorTests(unittest.TestCase):
    def test_add_returns_sum(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-2, 7), 5)

    def test_multiply_returns_product(self):
        self.assertEqual(multiply(3, 4), 12)
        self.assertEqual(multiply(-2, 5), -10)


if __name__ == "__main__":
    unittest.main()
