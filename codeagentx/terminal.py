"""Terminal output helpers that tolerate platform encoding differences."""

from __future__ import annotations

import sys
from typing import TextIO


def write_text(text: str, output: TextIO | None = None) -> None:
    """Write text without letting a console encoding error abort a run."""

    stream = output if output is not None else sys.stdout
    try:
        stream.write(str(text))
        stream.flush()
        return
    except UnicodeEncodeError:
        pass

    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe_text = str(text).encode(encoding, errors="replace").decode(
        encoding,
        errors="replace",
    )
    try:
        stream.write(safe_text)
        stream.flush()
    except UnicodeEncodeError:
        stream.write(str(text).encode("ascii", errors="replace").decode("ascii"))
        stream.flush()
