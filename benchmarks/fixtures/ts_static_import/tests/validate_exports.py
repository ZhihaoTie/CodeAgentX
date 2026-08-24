from pathlib import Path


source = Path("src/index.ts").read_text(encoding="utf-8").replace("'", '"')

errors = []
if "subtract" not in source:
    errors.append("src/index.ts should re-export subtract.")
if 'from "./math"' not in source and 'from "./math.ts"' not in source:
    errors.append("src/index.ts should re-export symbols from ./math.")

if errors:
    raise AssertionError("\n".join(errors))
