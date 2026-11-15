"""The shrink-only baseline: reading it, and judging a measurement.

Run: uv run -m unittest tests.test_baseline
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_shape_hooks import baseline as B


def _files(text: str) -> dict[str, int]:
    return B.parse(text, B.FILE_LENGTH, 1000)


def _functions(text: str) -> dict[str, int]:
    return B.parse(text, B.COMPLEXITY, 10)


class TestReadingTheBaseline(unittest.TestCase):
    def test_each_check_reads_its_own_table(self) -> None:
        text = (
            '[file-length]\n"a/b.py" = 1200\n'
            '[complexity]\n"src/x.rs::busy" = 14\n'
        )
        self.assertEqual(_files(text), {'a/b.py': 1200})
        self.assertEqual(_functions(text), {'src/x.rs::busy': 14})

    def test_the_other_table_is_not_validated(self) -> None:
        # Each hook knows only its own limit, which may be configured.
        text = '[file-length]\n"a.py" = 1200\n[complexity]\n"x.rs::f" = 9\n'
        self.assertEqual(_files(text), {'a.py': 1200})

    def test_an_empty_text_is_an_empty_baseline(self) -> None:
        self.assertEqual(_files(''), {})

    def test_a_missing_file_is_an_empty_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loaded = B.load(Path(tmp) / 'absent.toml', B.FILE_LENGTH, 1000)
        self.assertEqual(loaded, {})

    def test_a_leading_dot_slash_is_dropped(self) -> None:
        self.assertEqual(_files('[file-length]\n"./a.py" = 1200\n'),
                         {'a.py': 1200})

    def test_malformed_baselines_are_refused(self) -> None:
        cases = {
            'not toml': 'this is = = not toml',
            'unknown table': '[other]\n"a.py" = 1200\n',
            'table not a table': 'file-length = 3\n',
            'value not a number': '[file-length]\n"a.py" = "big"\n',
            'value a bool': '[file-length]\n"a.py" = true\n',
            'value a float': '[file-length]\n"a.py" = 1200.5\n',
            'absolute path': '[file-length]\n"/etc/a.py" = 1200\n',
            'parent path': '[file-length]\n"../a.py" = 1200\n',
            'empty path': '[file-length]\n"" = 1200\n',
            'duplicate once normalized':
                '[file-length]\n"a.py" = 1200\n"./a.py" = 1300\n',
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(B.BaselineError):
                _files(text)

    def test_a_complexity_key_needs_a_function(self) -> None:
        for text in ('[complexity]\n"src/x.rs" = 14\n',
                     '[complexity]\n"src/x.rs::" = 14\n',
                     '[complexity]\n"::f" = 14\n'):
            with self.subTest(text), self.assertRaises(B.BaselineError):
                _functions(text)

    def test_an_entry_within_the_limit_is_refused(self) -> None:
        with self.assertRaises(B.BaselineError) as ctx:
            _files('[file-length]\n"a.py" = 1000\n')
        self.assertIn('remove', str(ctx.exception))
        with self.assertRaises(B.BaselineError):
            _functions('[complexity]\n"a.rs::f" = 10\n')

    def test_a_baseline_that_cannot_be_read_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(B.BaselineError) as ctx:
                B.load(Path(tmp), B.FILE_LENGTH, 1000)
        self.assertIn('cannot be read', str(ctx.exception))

    def test_the_error_names_the_baseline_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'shape.toml'
            path.write_text('[file-length]\n"a.py" = "x"\n', encoding='utf-8')
            with self.assertRaises(B.BaselineError) as ctx:
                B.load(path, B.FILE_LENGTH, 1000)
        self.assertIn('shape.toml', str(ctx.exception))


class TestJudging(unittest.TestCase):
    def test_unlisted(self) -> None:
        self.assertIs(B.judge(900, None, 1000), B.Verdict.WITHIN)
        self.assertIs(B.judge(1000, None, 1000), B.Verdict.WITHIN)
        self.assertIs(B.judge(1001, None, 1000), B.Verdict.OVER)

    def test_listed(self) -> None:
        self.assertIs(B.judge(1500, 1500, 1000), B.Verdict.LISTED)
        self.assertIs(B.judge(1501, 1500, 1000), B.Verdict.GREW)
        self.assertIs(B.judge(1499, 1500, 1000), B.Verdict.SHRANK)
        self.assertIs(B.judge(1000, 1500, 1000), B.Verdict.CLEARED)

    def test_only_over_grew_shrank_and_cleared_fail(self) -> None:
        failing = {v for v in B.Verdict if v.fails}
        self.assertEqual(failing, {
            B.Verdict.OVER, B.Verdict.GREW, B.Verdict.SHRANK,
            B.Verdict.CLEARED,
        })


class TestEntryLines(unittest.TestCase):
    def test_a_line_is_valid_toml_for_its_key(self) -> None:
        line = B.entry_line('dir/a "q".py', 1200)
        self.assertEqual(line, '"dir/a \\"q\\".py" = 1200')
        self.assertEqual(_files(f'[file-length]\n{line}\n'),
                         {'dir/a "q".py': 1200})

    def test_a_table_lists_entries_sorted(self) -> None:
        text = B.render_table(B.FILE_LENGTH, {'b.py': 1300, 'a.py': 1200})
        self.assertEqual(
            text, '[file-length]\n"a.py" = 1200\n"b.py" = 1300\n'
        )


if __name__ == '__main__':
    unittest.main()
