"""check-complexity: no function over McCabe complexity 10.

Run: uv run -m unittest tests.test_complexity
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from code_shape_hooks import complexity as C


def _rust_fn(name: str, branches: int) -> str:
    """A Rust function whose cyclomatic complexity is 1 + *branches*."""
    body = ''.join(
        f'    if x == {i} {{ return {i}; }}\n' for i in range(branches)
    )
    return f'fn {name}(x: i32) -> i32 {{\n{body}    0\n}}\n'


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

    def baseline(self, text: str) -> None:
        self.write('code-shape-baseline.toml', text)

    def run_hook(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = C.main(list(argv))
        return code, out.getvalue()


class TestMeasuring(_Repo):
    def test_each_function_gets_its_complexity(self) -> None:
        rel = self.write('x.rs', _rust_fn('calm', 2) + _rust_fn('busy', 11))
        self.assertEqual(C.measure(rel), {'calm': (3, 1), 'busy': (12, 6)})

    def test_same_named_functions_keep_the_most_complex(self) -> None:
        text = (
            'struct A;\nstruct B;\n'
            'impl A {\n' + _rust_fn('new', 1) + '}\n'
            'impl B {\n' + _rust_fn('new', 12) + '}\n'
        )
        found = C.measure(self.write('x.rs', text))
        assert found is not None
        self.assertEqual(found['new'][0], 13)

    def test_a_language_lizard_cannot_read_is_skipped(self) -> None:
        self.assertIsNone(C.measure(self.write('notes.txt', 'if if if')))


class TestTheLimit(_Repo):
    def test_simple_functions_pass_quietly(self) -> None:
        code, out = self.run_hook(self.write('x.rs', _rust_fn('calm', 9)))
        self.assertEqual((code, out), (0, ''))

    def test_exactly_the_limit_passes(self) -> None:
        code, _out = self.run_hook(self.write('x.rs', _rust_fn('f', 9)))
        self.assertEqual(code, 0)

    def test_over_the_limit_fails_naming_the_function(self) -> None:
        code, out = self.run_hook(self.write('x.rs', _rust_fn('busy', 10)))
        self.assertEqual(code, 1)
        self.assertIn('x.rs:1: busy has complexity 11', out)

    def test_the_limit_can_be_set(self) -> None:
        rel = self.write('x.rs', _rust_fn('f', 5))
        code, _out = self.run_hook('--max-complexity', '5', rel)
        self.assertEqual(code, 1)

    def test_python_is_measured_too(self) -> None:
        body = ''.join(f'    if x == {i}:\n        return {i}\n'
                       for i in range(11))
        rel = self.write('m.py', f'def busy(x):\n{body}    return 0\n')
        code, out = self.run_hook(rel)
        self.assertEqual(code, 1)
        self.assertIn('busy has complexity 12', out)


class TestTheBaseline(_Repo):
    def test_a_listed_function_at_its_entry_passes(self) -> None:
        self.baseline('[complexity]\n"x.rs::busy" = 15\n')
        code, _out = self.run_hook(self.write('x.rs', _rust_fn('busy', 14)))
        self.assertEqual(code, 0)

    def test_a_listed_function_that_grew_fails(self) -> None:
        self.baseline('[complexity]\n"x.rs::busy" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('busy', 15)))
        self.assertEqual(code, 1)
        self.assertIn('grown past its baseline entry of 15', out)

    def test_a_listed_function_that_shrank_fails_naming_the_new_entry(
        self,
    ) -> None:
        self.baseline('[complexity]\n"x.rs::busy" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('busy', 12)))
        self.assertEqual(code, 1)
        self.assertIn('"x.rs::busy" = 13', out)

    def test_a_listed_function_now_within_the_limit_fails(self) -> None:
        self.baseline('[complexity]\n"x.rs::busy" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('busy', 3)))
        self.assertEqual(code, 1)
        self.assertIn('Remove its entry', out)

    def test_a_listed_function_that_is_gone_fails(self) -> None:
        self.baseline('[complexity]\n"x.rs::busy" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('calm', 1)))
        self.assertEqual(code, 1)
        self.assertIn('x.rs::busy', out)
        self.assertIn('no longer exists', out)

    def test_an_entry_for_a_file_that_is_gone_fails(self) -> None:
        self.baseline('[complexity]\n"gone.rs::busy" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('calm', 1)))
        self.assertEqual(code, 1)
        self.assertIn('gone.rs::busy', out)

    def test_a_malformed_baseline_fails_loudly(self) -> None:
        self.baseline('[complexity]\n"x.rs" = 15\n')
        code, out = self.run_hook(self.write('x.rs', _rust_fn('calm', 1)))
        self.assertEqual(code, 2)
        self.assertIn('code-shape-baseline.toml', out)


class TestPrintingABaseline(_Repo):
    def test_it_lists_only_functions_over_the_limit(self) -> None:
        rel = self.write(
            'x.rs', _rust_fn('calm', 2) + _rust_fn('busy', 13)
        )
        code, out = self.run_hook('--print-baseline', rel)
        self.assertEqual(code, 0)
        self.assertEqual(out, '[complexity]\n"x.rs::busy" = 14\n')


if __name__ == '__main__':
    unittest.main()
