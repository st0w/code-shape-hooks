"""check-baseline-ratchet: the baseline may shrink, never grow.

The other hooks hold each listed file or function to its baseline entry,
but the entries are only text: a change that raises an entry, or lists
a new file, passes them. This hook compares the baseline with its
version at a base revision and fails when an entry was raised or added.

Lowering or removing entries passes; the other hooks already require
that as code shrinks. One addition passes too: when a listed file moves
or a listed function is renamed, its key changes. An added entry may
take over a removed one whose file or function is gone from the tree,
if it is no larger, one for one and within the same table. That cannot
tell a move from deleting one file and adding another, but either way
the baseline lists no more, and nothing larger, than before.

Locally the base is ``HEAD``, so each commit is checked against its
parent. In CI, set ``CODE_SHAPE_BASE_REF`` to the branch a pull request
merges into, so its commits are checked together.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from code_shape_hooks import baseline as B
from code_shape_hooks.complexity import measure
from code_shape_hooks.report import EXIT_UNUSABLE, Report

#: Names the base revision when ``--base-ref`` is not given.
BASE_REF_ENV = 'CODE_SHAPE_BASE_REF'

#: The base revision when neither is set: the parent of a new commit.
DEFAULT_BASE_REF = 'HEAD'

#: Whether a table's key has left the tree: ``gone(table, key)``.
Gone = Callable[[str, str], bool]


class RatchetError(Exception):
    """The comparison cannot be made: a bad revision or baseline."""


def compare(base: str | None, current: str, *, gone: Gone) -> list[str]:
    """
    What grew in the baseline since its base version.

    :param base: The baseline at the base revision, or ``None`` if it
        had none (adopting a baseline is allowed).
    :param current: The baseline now.
    :param gone: Whether a key's file or function has left the tree.
    :returns: One line per raised or added entry.
    :raises RatchetError: If either version is malformed.
    """
    if base is None:
        _parse_all(current, 'the current version')
        return []
    old = _parse_all(base, 'the base version')
    new = _parse_all(current, 'the current version')
    errors: list[str] = []
    for table in B.TABLES:
        errors += _compare_table(table, old[table], new[table], gone)
    return errors


def is_gone(table: str, key: str) -> bool:
    """
    Whether a baseline key's file, or function, has left the tree.

    :param table: :data:`~code_shape_hooks.baseline.FILE_LENGTH` or
        :data:`~code_shape_hooks.baseline.COMPLEXITY`.
    :param key: A path, or ``path::function``.
    :returns: True if the file is missing, or the function is not in it.
    """
    path = B.key_path(key)
    if not Path(path).is_file():
        return True
    if table == B.FILE_LENGTH:
        return False
    found = measure(path)
    function = key.partition(B.FUNCTION_SEPARATOR)[2]
    return found is None or function not in found


def read_at_ref(ref: str, path: str) -> str | None:
    """
    A file's contents at a git revision, read-only.

    :param ref: The revision, e.g. ``HEAD`` or ``origin/main``.
    :param path: The file, relative to the repository root.
    :returns: Its text, or ``None`` if it did not exist there.
    :raises RatchetError: If *ref* is not a commit, git cannot run, or
        the file is not UTF-8.
    """
    if not ref or ref.startswith('-'):
        raise RatchetError(f'{ref!r} is not a git revision')
    resolved = _git('rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
    if resolved.returncode != 0:
        raise RatchetError(
            f'{ref!r} is not a commit in this repository (in CI, fetch it '
            f'first; a shallow clone may not have it)'
        )
    blob = f'{resolved.stdout.strip()}:{path}'
    if _git('cat-file', '-e', blob).returncode != 0:
        return None
    shown = _git('cat-file', 'blob', blob)
    if shown.returncode != 0:
        raise RatchetError(f'cannot read it at {ref!r}: {shown.stderr}')
    return shown.stdout


def main(argv: Sequence[str] | None = None) -> int:
    """
    Compare the baseline with its version at the base revision.

    :param argv: Arguments; ``None`` reads the command line.
    :returns: The exit status.
    """
    args = _parse_args(argv)
    try:
        path = B.normalize(args.baseline)
        current = _read_current(path)
        base = read_at_ref(args.base_ref, path)
        errors = compare(base, current, gone=is_gone)
    except (RatchetError, B.BaselineError) as exc:
        print(f'error: {args.baseline}: {exc}')
        return EXIT_UNUSABLE
    return Report(errors=errors).emit()


def _compare_table(
    table: str, old: dict[str, int], new: dict[str, int], gone: Gone
) -> list[str]:
    errors: list[str] = []
    added: list[str] = []
    for key in sorted(new):
        if key not in old:
            added.append(key)
        elif new[key] > old[key]:
            errors.append(
                f'[{table}] {key!r} was raised from {old[key]} to '
                f'{new[key]}. An entry may only be lowered: shrink the '
                f'code instead.'
            )
    # Entries whose code moved, largest first. Matching the largest
    # added entry to the largest of these, greedily, covers as many
    # added entries as any pairing can.
    moved = sorted(
        (old[k] for k in old if k not in new and gone(table, k)),
        reverse=True,
    )
    for key in sorted(added, key=lambda k: (-new[k], k)):
        if moved and moved[0] >= new[key]:
            moved.pop(0)
            continue
        errors.append(
            f'[{table}] {key!r} = {new[key]} was added. The baseline only '
            f'lists what was over the limit when it was adopted: split '
            f'the code instead. (A moved file or renamed function keeps '
            f'its entry only if its old one is removed and no smaller.)'
        )
    return errors


def _parse_all(text: str, which: str) -> dict[str, dict[str, int]]:
    # The configured limits are the other hooks' to check; any positive
    # size is a well-formed entry here.
    try:
        return {table: B.parse(text, table, 0) for table in B.TABLES}
    except B.BaselineError as exc:
        raise RatchetError(f'{which}: {exc}') from exc


def _read_current(path: str) -> str:
    try:
        return Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''
    except (OSError, UnicodeDecodeError) as exc:
        raise RatchetError(f'cannot be read: {exc}') from exc


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ['git', *args],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise RatchetError(f'git {args[0]} failed: {exc}') from exc


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='check-baseline-ratchet', description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        '--base-ref',
        default=os.environ.get(BASE_REF_ENV) or DEFAULT_BASE_REF,
        help=f'revision to compare with (default: ${BASE_REF_ENV}, '
        f'else {DEFAULT_BASE_REF})',
    )
    parser.add_argument('--baseline', default=B.DEFAULT_PATH)
    return parser.parse_args(argv)


if __name__ == '__main__':
    raise SystemExit(main())
