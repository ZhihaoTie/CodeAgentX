from pathlib import Path


source = Path("src/routes.ts").read_text(encoding="utf-8").replace("'", '"')

errors = []
if "encodeURIComponent(id)" not in source:
    errors.append("buildUserPath should encode the user id.")
if "encodeURIComponent(tab)" not in source:
    errors.append("buildUserPath should encode the optional tab.")
if "?tab=" not in source:
    errors.append("buildUserPath should append tab as a query parameter.")
if "if (tab" not in source and "tab ?" not in source:
    errors.append("buildUserPath should only append the tab query when tab is provided.")

if errors:
    raise AssertionError("\n".join(errors))
