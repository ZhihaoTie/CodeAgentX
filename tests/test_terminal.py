from __future__ import annotations

import io
import unittest

from codeagentx.terminal import write_text


class TerminalOutputTests(unittest.TestCase):
    def test_writes_unicode_to_normal_stream(self):
        output = io.StringIO()

        write_text("中文 \ufffd", output)

        self.assertEqual(output.getvalue(), "中文 \ufffd")

    def test_replaces_characters_unsupported_by_stream_encoding(self):
        output = io.TextIOWrapper(io.BytesIO(), encoding="ascii")

        write_text("hello \u4e16\u754c", output)
        output.flush()

        self.assertEqual(output.buffer.getvalue(), b"hello ??")
        output.detach()


if __name__ == "__main__":
    unittest.main()
