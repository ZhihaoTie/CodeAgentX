from shop.discounts import discount_rate


def order_total(items, discount_code="NONE"):
    subtotal = sum(item["unit_price"] for item in items)
    return round(subtotal - discount_rate(discount_code), 2)
