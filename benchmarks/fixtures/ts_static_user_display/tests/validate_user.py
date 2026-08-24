from pathlib import Path


source = Path("src/user.ts").read_text(encoding="utf-8")

errors = []
if "nickname?" not in source:
    errors.append("User should keep nickname as an optional field.")
if "user.nickname" not in source:
    errors.append("displayUser should prefer nickname when present.")
if "user.email" not in source:
    errors.append("displayUser should include the email address.")
if "??" not in source and "||" not in source:
    errors.append("displayUser should fall back from nickname to name.")

if errors:
    raise AssertionError("\n".join(errors))
