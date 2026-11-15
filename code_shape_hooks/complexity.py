"""check-complexity: no function over McCabe complexity 10.

For languages without a linter that enforces this (Python projects
should use ruff's C901 instead). Complexity comes from lizard, which
counts each branch, loop, ``match`` arm and boolean operator.

A function is keyed in the baseline as ``path::name``. Names are not
unique within a file (two ``impl`` blocks may each have ``new``), so
all functions sharing a key are held to its entry, and the most complex
one is what is compared and reported.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import lizard

from code_shape_hooks import baseline as B
from code_shape_hooks.report import (
    EXIT_UNUSABLE,
    Report,
    load_baseline,
    missing_files,
)

DEFAULT_MAX_COMPLEXITY = 10

#: A file's functions: name to (complexity, start line).
_Scores = dict[str, tuple[int, int]]


def measure(path: str) -> dict[str, tuple[int, int]] | None:
    """
    Each function's complexity in a file.

    :param path: The file.
    :returns: ``{name: (complexity, start line)}``, keeping the most
        complex of same-named functions; ``None`` for a file lizard has
        no reader for.
    """
    if lizard.get_reader_for(path) is None:
        return None
    found: dict[str, tuple[int, int]] = {}
    for function in lizard.analyze_file(path).function_list:
        score = function.cyclomatic_complexity
        if function.name not in found or score > found[function.name][0]:
            found[function.name] = (score, function.start_line)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the hook on the files pre-commit passes.

    :param argv: Arguments; ``None`` reads the command line.
    :returns: The exit status.
    """
    args = _parse_args(argv)
    scores = _measure_all(args.filenames)
    if args.print_baseline:
        over = {
            B.function_key(path, name): score
            for path, found in scores.items()
            for name, (score, _line) in found.items()
            if score > args.max_complexity
        }
        print(B.render_table(B.COMPLEXITY, over), end='')
        return 0
    entries = load_baseline(args.baseline, B.COMPLEXITY, args.max_complexity)
    if entries is None:
        return EXIT_UNUSABLE
    report = Report(errors=missing_files(entries, args.baseline))
    for path in sorted(scores):
        _judge_file(report, path, scores[path], entries, args)
    return report.emit()


def _judge_file(
    report: Report,
    path: str,
    found: dict[str, tuple[int, int]],
    entries: dict[str, int],
    args: argparse.Namespace,
) -> None:
    for name in sorted(found):
        score, line = found[name]
        key = B.function_key(path, name)
        message = _message(
            f'{path}:{line}: {name} has complexity {score}',
            B.judge(score, entries.get(key), args.max_complexity),
            key, score, entries.get(key), args,
        )
        if message is not None:
            report.errors.append(message)
    for key in sorted(entries):
        if B.key_path(key) == path and key.split('::', 1)[1] not in found:
            report.errors.append(
                f'{key}: listed in {args.baseline} but no longer exists. '
                f'Remove its entry.'
            )


def _message(
    head: str,
    verdict: B.Verdict,
    key: str,
    score: int,
    entry: int | None,
    args: argparse.Namespace,
) -> str | None:
    limit = args.max_complexity
    if verdict is B.Verdict.OVER:
        return f'{head}, over the limit of {limit}. Split it up.'
    if verdict is B.Verdict.GREW:
        return (
            f'{head}, grown past its baseline entry of {entry}. A listed '
            f'function may only get simpler.'
        )
    if verdict is B.Verdict.SHRANK:
        return (
            f'{head}, under its baseline entry of {entry}. Lock that in by '
            f'setting its entry in {args.baseline} to: '
            f'{B.entry_line(key, score)}'
        )
    if verdict is B.Verdict.CLEARED:
        return (
            f'{head}, now within the limit of {limit}. Remove its entry '
            f'from {args.baseline}.'
        )
    return None


def _measure_all(filenames: Sequence[str]) -> dict[str, _Scores]:
    scores: dict[str, _Scores] = {}
    for name in filenames:
        found = measure(name)
        if found is not None:
            relative = os.path.relpath(name) if os.path.isabs(name) else name
            scores[B.normalize(relative)] = found
    return scores


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='check-complexity', description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        '--max-complexity', type=int, default=DEFAULT_MAX_COMPLEXITY
    )
    parser.add_argument('--baseline', default=B.DEFAULT_PATH)
    parser.add_argument(
        '--print-baseline',
        action='store_true',
        help='print a [complexity] table for the functions over the limit',
    )
    parser.add_argument('filenames', nargs='*')
    args = parser.parse_args(argv)
    if args.max_complexity < 1:
        parser.error('--max-complexity must be positive')
    return args


if __name__ == '__main__':
    raise SystemExit(main())
