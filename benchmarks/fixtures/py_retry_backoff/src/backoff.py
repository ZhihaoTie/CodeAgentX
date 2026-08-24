def retry_delays(attempts, base=1.0, cap=30.0):
    return [base * (2 ** index) for index in range(attempts + 1)]
