def discount_rate(code):
    rates = {
        "NONE": 0.0,
        "SAVE10": 0.10,
        "VIP": 0.20,
    }
    return rates.get(code, 0.0)
