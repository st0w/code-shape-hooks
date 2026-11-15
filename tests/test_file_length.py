"""check-file-length: the 1,000-line cap, 350-line aim and baseline.

Run: uv run -m unittest tests.test_file_length
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from code_shape_hooks import file_length as F


def _lines(count: int, *, trailing_newline: bool = True) -> str:
    text = '\n'.join(f'x = {i}' for i in range(count))
    return text + '\n' if trailing_newline and count else text


class TestCountingLines(unittest.TestCase):
    def test_lines_are_counted_with_or_without_a_final_newline(self) -> None:
        self.assertEqual(F.count_lines(b''), 0)
        self.assertEqual(F.count_lines(b'a\n'), 1)
        self.assertEqual(F.count_lines(b'a\nb'), 2)
        self.assertEqual(F.count_lines(b'\n\n'), 2)


class _Repo(unittest.TestCase):
    """A scratch repository root, made the working directory."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)

    def write(self, rel: str, text: str) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return rel

    def run_hook(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = F.main(list(argv))
        return code, out.getvalue()


class TestTheLimit(_Repo):
    def test_a_short_file_passes_quietly(self) -> None:
        code, out = self.run_hook(self.write('a.py', _lines(300)))
        self.assertEqual((code, out), (0, ''))

    def test_over_the_aim_passes_with_a_note(self) -> None:
        code, out = self.run_hook(self.write('a.py', _lines(351)))
        self.assertEqual(code, 0)
        self.assertIn('a.py: 351 lines', out)
        self.assertIn('350', out)

    def test_exactly_the_limit_passes(self) -> None:
        code, _out = self.run_hook(self.write('a.py', _lines(1000)))
        self.assertEqual(code, 0)

    def test_over_the_limit_fails(self) -> None:
        code, out = self.run_hook(self.write('a.py', _lines(1001)))
        self.assertEqual(code, 1)
        self.assertIn('a.py: 1001 lines, over the 1000-line limit', out)

    def test_every_file_is_reported(self) -> None:
        code, out = self.run_hook(
            self.write('a.py', _lines(1001)),
            self.write('b/c.rs', _lines(1002)),
        )
        self.assertEqual(code, 1)
        self.assertIn('a.py:', out)
        self.assertIn('b/c.rs:', out)

    def test_a_file_that_cannot_be_read_fails_naming_it(self) -> None:
        code, out = self.run_hook('missing.py')
        self.assertEqual(code, 1)
        self.assertIn('missing.py: cannot be read', out)

    def test_the_limits_can_be_set(self) -> None:
        rel = self.write('a.py', _lines(60))
        code, out = self.run_hook(
            '--max-lines', '50', '--target-lines', '20', rel
        )
        self.assertEqual(code, 1)
        self.assertIn('over the 50-line limit', out)

    def test_an_aim_at_or_over_the_limit_is_refused(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                F.main(['--max-lines', '50', '--target-lines', '50'])
        self.assertEqual(ctx.exception.code, 2)


class TestTheBaseline(_Repo):
    def baseline(self, text: str) -> None:
        self.write('code-shape-baseline.toml', text)

    def test_a_listed_file_at_its_entry_passes_with_a_note(self) -> None:
        self.baseline('[file-length]\n"big.py" = 1500\n')
        code, out = self.run_hook(self.write('big.py', _lines(1500)))
        self.assertEqual(code, 0)
        self.assertIn('big.py: 1500 lines', out)

    def test_a_listed_file_that_grew_fails(self) -> None:
        self.baseline('[file-length]\n"big.py" = 1500\n')
        code, out = self.run_hook(self.write('big.py', _lines(1501)))
        self.assertEqual(code, 1)
        self.assertIn('grown past its baseline entry of 1500', out)

    def test_a_listed_file_that_shrank_fails_naming_the_new_entry(
        self,
    ) -> None:
        self.baseline('[file-length]\n"big.py" = 1500\n')
        code, out = self.run_hook(self.write('big.py', _lines(1400)))
        self.assertEqual(code, 1)
        self.assertIn('"big.py" = 1400', out)

    def test_a_listed_file_now_within_the_limit_fails_until_removed(
        self,
    ) -> None:
        self.baseline('[file-length]\n"big.py" = 1500\n')
        code, out = self.run_hook(self.write('big.py', _lines(900)))
        self.assertEqual(code, 1)
        self.assertIn('Remove its entry', out)

    def test_an_entry_for_a_file_that_is_gone_fails(self) -> None:
        self.baseline('[file-length]\n"gone.py" = 1500\n')
        code, out = self.run_hook(self.write('a.py', _lines(10)))
        self.assertEqual(code, 1)
        self.assertIn('gone.py', out)
        self.assertIn('no longer exists', out)

    def test_entries_for_files_not_passed_are_not_measured(self) -> None:
        self.baseline('[file-length]\n"big.py" = 1500\n')
        self.write('big.py', _lines(1600))
        code, _out = self.run_hook(self.write('a.py', _lines(10)))
        self.assertEqual(code, 0)

    def test_a_baseline_path_can_be_given(self) -> None:
        self.write('conf/shape.toml', '[file-length]\n"big.py" = 1500\n')
        code, _out = self.run_hook(
            '--baseline', 'conf/shape.toml',
            self.write('big.py', _lines(1500)),
        )
        self.assertEqual(code, 0)

    def test_a_malformed_baseline_fails_loudly(self) -> None:
        self.baseline('[file-length]\n"big.py" = "lots"\n')
        code, out = self.run_hook(self.write('a.py', _lines(10)))
        self.assertEqual(code, 2)
        self.assertIn('code-shape-baseline.toml', out)


class TestPrintingABaseline(_Repo):
    def test_it_lists_only_files_over_the_limit(self) -> None:
        code, out = self.run_hook(
            '--print-baseline',
            self.write('b.py', _lines(1200)),
            self.write('a.py', _lines(1100)),
            self.write('c.py', _lines(500)),
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            out, '[file-length]\n"a.py" = 1100\n"b.py" = 1200\n'
        )


if __name__ == '__main__':
    unittest.main()
