import unittest

from shop.cart import order_total


class OrderTotalTests(unittest.TestCase):
    def test_applies_quantity_before_discount(self):
        items = [
            {"name": "notebook", "unit_price": 10.0, "quantity": 2},
            {"name": "pen", "unit_price": 5.0, "quantity": 1},
        ]

        self.assertEqual(order_total(items, "SAVE10"), 22.5)

    def test_unknown_discount_keeps_subtotal(self):
        items = [{"name": "bag", "unit_price": 30.0, "quantity": 3}]

        self.assertEqual(order_total(items, "MISSING"), 90.0)


if __name__ == "__main__":
    unittest.main()
