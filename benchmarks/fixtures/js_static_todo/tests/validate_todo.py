from pathlib import Path


source = Path("todo.js").read_text(encoding="utf-8")

errors = []
if "item.id === id" not in source and "item.id == id" not in source:
    errors.append("toggleTodo should compare each item id with the requested id.")
if "completed: !item.completed" not in source:
    errors.append("toggleTodo should invert the matched item's completed flag.")
if "completed: true" in source:
    errors.append("toggleTodo should not mark every item as completed.")

if errors:
    raise AssertionError("\n".join(errors))
