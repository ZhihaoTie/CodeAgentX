def summarize_sales(rows):
    total = 0
    count = 0
    for row in rows:
        total += row["amount"]
        count += 1

    return {"count": count, "total": total, "average": total / count}
