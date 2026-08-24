from pathlib import Path


source = Path("items.js").read_text(encoding="utf-8")

errors = []
if ".filter(" not in source:
    errors.append("visibleItems should filter the item list.")
if "!item.hidden" not in source:
    errors.append("visibleItems should exclude hidden items.")
if "!item.archived" not in source:
    errors.append("visibleItems should exclude archived items.")
if "deleted" in source:
    errors.append("visibleItems should not rely on a deleted flag.")

if errors:
    raise AssertionError("\n".join(errors))
