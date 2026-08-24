from pathlib import Path


source = Path("todo_list.js").read_text(encoding="utf-8")

errors = []
if ".filter(" not in source:
    errors.append("removeTodo should use filter to return a new array.")
if "item.id !== id" not in source and "item.id != id" not in source:
    errors.append("removeTodo should keep items whose id does not match the removed id.")
if ".splice(" in source:
    errors.append("removeTodo should not mutate the input array with splice.")
if "return items;" in source:
    errors.append("removeTodo should not return the original array unchanged.")

if errors:
    raise AssertionError("\n".join(errors))
