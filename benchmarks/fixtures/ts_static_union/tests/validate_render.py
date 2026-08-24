from pathlib import Path


source = Path("src/render.ts").read_text(encoding="utf-8").replace("'", '"')

has_success_branch = 'result.kind === "success"' in source or 'case "success"' in source
has_error_branch = 'result.kind === "error"' in source or 'case "error"' in source

errors = []
if not has_success_branch:
    errors.append("renderResult should branch on the success variant.")
if not has_error_branch:
    errors.append("renderResult should branch on the error variant.")
if "result.value" not in source:
    errors.append("renderResult should use the success value.")
if "result.message" not in source:
    errors.append("renderResult should use the error message.")

if errors:
    raise AssertionError("\n".join(errors))
