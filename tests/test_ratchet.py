"""check-baseline-ratchet: the baseline may shrink, never grow.

Run: uv run --locked --no-sync -m unittest tests.test_ratchet
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from code_shape_hooks import ratchet as R

_FILES = '[file-length]\n'
_FUNCS = '[complexity]\n'


_Gone = Callable[[str, str], bool]


def _never_gone(_table: str, _key: str) -> bool:
    return False


def _gone(*keys: str) -> _Gone:
    """A stand-in for the tree: only *keys* are gone from it."""

    def gone(_table: str, key: str) -> bool:
        return key in keys

    return gone


class TestComparing(unittest.TestCase):
    def check(
        self, base: str | None, current: str, gone: _Gone = _never_gone
    ) -> list[str]:
        return R.compare(base, current, gone=gone)

    def test_adopting_a_baseline_is_allowed(self) -> None:
        self.assertEqual(self.check(None, _FILES + '"a.py" = 1500\n'), [])

    def test_unchanged_lowered_and_removed_entries_pass(self) -> None:
        base = _FILES + '"a.py" = 1500\n"b.py" = 1200\n'
        for current in (base, _FILES + '"a.py" = 1400\n"b.py" = 1200\n',
                        _FILES + '"a.py" = 1500\n', ''):
            with self.subTest(current=current):
                self.assertEqual(self.check(base, current), [])

    def test_a_raised_entry_fails(self) -> None:
        errors = self.check(_FILES + '"a.py" = 1500\n',
                            _FILES + '"a.py" = 1501\n')
        self.assertEqual(len(errors), 1)
        self.assertIn('a.py', errors[0])
        self.assertIn('1500', errors[0])
        self.assertIn('1501', errors[0])

    def test_an_added_entry_fails(self) -> None:
        errors = self.check(_FILES + '"a.py" = 1500\n',
                            _FILES + '"a.py" = 1500\n"new.py" = 1100\n')
        self.assertEqual(len(errors), 1)
        self.assertIn('new.py', errors[0])
        self.assertIn('added', errors[0])

    def test_a_moved_file_keeps_its_entry_under_its_new_name(self) -> None:
        errors = self.check(_FILES + '"old.py" = 1500\n',
                            _FILES + '"new.py" = 1400\n', _gone('old.py'))
        self.assertEqual(errors, [])

    def test_a_moved_file_may_not_grow(self) -> None:
        errors = self.check(_FILES + '"old.py" = 1500\n',
                            _FILES + '"new.py" = 1600\n', _gone('old.py'))
        self.assertEqual(len(errors), 1)

    def test_a_cleared_entry_cannot_vouch_for_new_code(self) -> None:
        # old.py shrank within the limit and still exists: its entry
        # going away is progress, not a move.
        errors = self.check(_FILES + '"old.py" = 1500\n',
                            _FILES + '"new.py" = 1400\n')
        self.assertEqual(len(errors), 1)

    def test_one_moved_entry_covers_one_new_entry(self) -> None:
        errors = self.check(
            _FILES + '"old.py" = 1500\n',
            _FILES + '"a.py" = 1100\n"b.py" = 1100\n', _gone('old.py'),
        )
        self.assertEqual(len(errors), 1)

    def test_a_renamed_function_keeps_its_entry(self) -> None:
        errors = self.check(_FUNCS + '"x.rs::old" = 15\n',
                            _FUNCS + '"x.rs::new" = 14\n', _gone('x.rs::old'))
        self.assertEqual(errors, [])

    def test_entries_only_move_within_their_table(self) -> None:
        errors = self.check(_FILES + '"x.rs" = 1500\n',
                            _FUNCS + '"y.rs::f" = 14\n', _gone('x.rs'))
        self.assertEqual(len(errors), 1)

    def test_a_malformed_baseline_is_refused(self) -> None:
        for base, current in ((None, '[file-length]\n"a.py" = "x"\n'),
                              ('not = = toml', _FILES)):
            with self.subTest(base=base), self.assertRaises(R.RatchetError):
                self.check(base, current)


class TestWhatIsGone(unittest.TestCase):
    """Whether a removed entry's file or function left the tree."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp.name)
        Path('kept.py').write_text('x = 1\n', encoding='utf-8')
        Path('lib.rs').write_text(
            'fn kept(x: i32) -> i32 {\n    x\n}\n', encoding='utf-8'
        )

    def test_a_file_that_still_exists_is_not_gone(self) -> None:
        self.assertFalse(R.is_gone('file-length', 'kept.py'))

    def test_a_deleted_or_moved_file_is_gone(self) -> None:
        self.assertTrue(R.is_gone('file-length', 'moved.py'))

    def test_a_function_still_in_its_file_is_not_gone(self) -> None:
        self.assertFalse(R.is_gone('complexity', 'lib.rs::kept'))

    def test_a_renamed_function_is_gone(self) -> None:
        self.assertTrue(R.is_gone('complexity', 'lib.rs::renamed'))

    def test_a_function_whose_file_is_gone_is_gone(self) -> None:
        self.assertTrue(R.is_gone('complexity', 'moved.rs::kept'))


class TestReadingTheBase(unittest.TestCase):
    """Read-only git, against this repository's own history."""

    def test_a_file_at_a_ref_is_read(self) -> None:
        text = R.read_at_ref('HEAD', 'pyproject.toml')
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn('code-shape-hooks', text)

    def test_a_file_missing_at_the_ref_is_none(self) -> None:
        self.assertIsNone(R.read_at_ref('HEAD', 'no-such-baseline.toml'))

    def test_an_unknown_ref_is_an_error(self) -> None:
        with self.assertRaises(R.RatchetError) as ctx:
            R.read_at_ref('no-such-ref-for-sure', 'pyproject.toml')
        self.assertIn('no-such-ref-for-sure', str(ctx.exception))

    def test_a_ref_that_looks_like_an_option_is_refused(self) -> None:
        for ref in ('-x', '--output=/tmp/x', ''):
            with self.subTest(ref=ref), self.assertRaises(R.RatchetError):
                R.read_at_ref(ref, 'pyproject.toml')


class TestTheHook(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp.name)
        self.root = Path(tmp.name)
        self.reads: list[tuple[str, str]] = []

    def run_hook(self, base: str | None, current: str, *argv: str,
                 env: dict[str, str] | None = None) -> tuple[int, str]:
        (self.root / 'code-shape-baseline.toml').write_text(
            current, encoding='utf-8'
        )

        def read(ref: str, path: str) -> str | None:
            self.reads.append((ref, path))
            return base

        out = io.StringIO()
        with mock.patch.object(R, 'read_at_ref', side_effect=read), \
                mock.patch.dict(os.environ, env or {}, clear=False), \
                contextlib.redirect_stdout(out):
            code = R.main(list(argv))
        return code, out.getvalue()

    def test_it_compares_with_head_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(R.BASE_REF_ENV, None)
            code, _out = self.run_hook(_FILES, _FILES)
        self.assertEqual(code, 0)
        self.assertEqual(self.reads, [('HEAD', 'code-shape-baseline.toml')])

    def test_ci_sets_the_base_ref_in_the_environment(self) -> None:
        self.run_hook(_FILES, _FILES, env={R.BASE_REF_ENV: 'origin/main'})
        self.assertEqual(self.reads[0][0], 'origin/main')

    def test_an_argument_beats_the_environment(self) -> None:
        self.run_hook(_FILES, _FILES, '--base-ref', 'v1',
                      env={R.BASE_REF_ENV: 'origin/main'})
        self.assertEqual(self.reads[0][0], 'v1')

    def test_a_raised_entry_fails_the_hook(self) -> None:
        code, out = self.run_hook(_FILES + '"a.py" = 1500\n',
                                  _FILES + '"a.py" = 1600\n')
        self.assertEqual(code, 1)
        self.assertIn('error: ', out)

    def test_a_malformed_baseline_fails_loudly(self) -> None:
        code, out = self.run_hook(None, '[file-length]\n"a.py" = "x"\n')
        self.assertEqual(code, 2)
        self.assertIn('code-shape-baseline.toml', out)

    def test_an_unknown_base_ref_fails_loudly(self) -> None:
        def read(ref: str, _path: str) -> str | None:
            raise R.RatchetError(f'{ref!r} is not a commit')

        out = io.StringIO()
        with mock.patch.object(R, 'read_at_ref', side_effect=read), \
                contextlib.redirect_stdout(out):
            code = R.main(['--base-ref', 'nope'])
        self.assertEqual(code, 2)
        self.assertIn("'nope'", out.getvalue())

    def test_a_missing_baseline_is_an_empty_one(self) -> None:
        def read(_ref: str, _path: str) -> str | None:
            return _FILES + '"a.py" = 1500\n'

        with mock.patch.object(R, 'read_at_ref', side_effect=read), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main([]), 0)


if __name__ == '__main__':
    unittest.main()
