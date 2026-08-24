def moving_average(values, window):
    averages = []
    total = 0
    for index, value in enumerate(values, start=1):
        total += value
        averages.append(total / index)
    return averages
