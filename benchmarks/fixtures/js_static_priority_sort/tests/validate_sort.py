from pathlib import Path


source = Path("tasks.js").read_text(encoding="utf-8")

errors = []
if "priority" not in source:
    errors.append("sortTasks should compare task priority.")
if ".sort(" not in source:
    errors.append("sortTasks should sort the copied task list.")
if ".slice()" not in source and "[...tasks]" not in source and "Array.from(tasks)" not in source:
    errors.append("sortTasks should copy the input before sorting.")
if "createdAt" in source:
    errors.append("sortTasks should not sort by creation time.")

if errors:
    raise AssertionError("\n".join(errors))
