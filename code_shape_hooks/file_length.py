"""check-file-length: no code file over 1,000 lines; aim for 350.

Long files are hard for people and coding agents alike to read whole,
and a file that keeps growing usually holds more than one
responsibility. A file over the limit fails; one over the aim passes
with a note, so the nudge to split comes before the hard stop. Files
over the limit when it was adopted are listed in the shrink-only
baseline (see :mod:`code_shape_hooks.baseline`).

Lines are physical lines, comments and docstrings included: they are
part of what a reader has to get through.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from code_shape_hooks import baseline as B
from code_shape_hooks.report import (
    EXIT_UNUSABLE,
    Report,
    load_baseline,
    missing_files,
)

DEFAULT_MAX_LINES = 1000
DEFAULT_TARGET_LINES = 350


def count_lines(data: bytes) -> int:
    """
    The number of lines in a file's contents.

    :param data: The bytes.
    :returns: Newline-terminated lines, plus an unterminated last one.
    """
    trailing = 1 if data and not data.endswith(b'\n') else 0
    return data.count(b'\n') + trailing


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the hook on the files pre-commit passes.

    :param argv: Arguments; ``None`` reads the command line.
    :returns: The exit status.
    """
    args = _parse_args(argv)
    sizes, unreadable = _measure(args.filenames)
    if args.print_baseline:
        over = {k: v for k, v in sizes.items() if v > args.max_lines}
        print(B.render_table(B.FILE_LENGTH, over), end='')
        return 0
    entries = load_baseline(args.baseline, B.FILE_LENGTH, args.max_lines)
    if entries is None:
        return EXIT_UNUSABLE
    report = Report(errors=unreadable + missing_files(entries, args.baseline))
    for path in sorted(sizes):
        _judge(report, path, sizes[path], entries.get(path), args)
    return report.emit()


def _judge(
    report: Report,
    path: str,
    lines: int,
    entry: int | None,
    args: argparse.Namespace,
) -> None:
    limit = args.max_lines
    verdict = B.judge(lines, entry, limit)
    head = f'{path}: {lines} lines'
    if verdict is B.Verdict.OVER:
        report.errors.append(
            f'{head}, over the {limit}-line limit. Split it by '
            f'responsibility.'
        )
    elif verdict is B.Verdict.GREW:
        report.errors.append(
            f'{head}, grown past its baseline entry of {entry}. A listed '
            f'file may only shrink.'
        )
    elif verdict is B.Verdict.SHRANK:
        report.errors.append(
            f'{head}, under its baseline entry of {entry}. Lock that in '
            f'by setting its entry in {args.baseline} to: '
            f'{B.entry_line(path, lines)}'
        )
    elif verdict is B.Verdict.CLEARED:
        report.errors.append(
            f'{head}, now within the {limit}-line limit. Remove its '
            f'entry from {args.baseline}.'
        )
    elif verdict is B.Verdict.LISTED:
        report.notes.append(
            f'{head}, listed in the baseline. Shrink it below {limit}.'
        )
    elif lines > args.target_lines:
        report.notes.append(
            f'{head}. Aim for {args.target_lines} or fewer: split it by '
            f'responsibility before it grows.'
        )


def _measure(names: Sequence[str]) -> tuple[dict[str, int], list[str]]:
    sizes: dict[str, int] = {}
    unreadable: list[str] = []
    for name in names:
        try:
            with open(name, 'rb') as handle:
                lines = count_lines(handle.read())
        except OSError as exc:
            unreadable.append(f'{name}: cannot be read: {exc.strerror}')
            continue
        sizes[B.normalize(_relative(name))] = lines
    return sizes, unreadable


def _relative(name: str) -> str:
    return os.path.relpath(name) if os.path.isabs(name) else name


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='check-file-length', description=__doc__.splitlines()[0]
    )
    parser.add_argument('--max-lines', type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument(
        '--target-lines', type=int, default=DEFAULT_TARGET_LINES
    )
    parser.add_argument('--baseline', default=B.DEFAULT_PATH)
    parser.add_argument(
        '--print-baseline',
        action='store_true',
        help='print a [file-length] table for the files over the limit',
    )
    parser.add_argument('filenames', nargs='*')
    args = parser.parse_args(argv)
    if not 0 < args.target_lines < args.max_lines:
        parser.error('--target-lines must be positive and under --max-lines')
    return args


if __name__ == '__main__':
    raise SystemExit(main())
