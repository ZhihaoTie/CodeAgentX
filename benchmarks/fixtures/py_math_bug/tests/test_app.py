import unittest

from app import add, multiply


class MathFunctionTests(unittest.TestCase):
    def test_adds_positive_numbers(self):
        self.assertEqual(add(2, 3), 5)

    def test_adds_negative_numbers(self):
        self.assertEqual(add(-2, -3), -5)

    def test_multiplies_numbers(self):
        self.assertEqual(multiply(4, 5), 20)


if __name__ == "__main__":
    unittest.main()
