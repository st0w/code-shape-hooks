"""The shrink-only baseline: what was over a limit when it was adopted.

A repository adopting a limit usually has some files or functions over
it already. Failing every commit that touches them would block all work
on exactly the code that most needs it, so each one is listed with its
size at the time. A listed item may shrink but never grow, and its entry
must be lowered as it shrinks (or a later change could quietly regrow
it), until it is within the limit and its entry is removed.

The file, ``code-shape-baseline.toml`` at the repository root by
default, has one table per check:

    [file-length]
    "src/big_module.py" = 1480

    [complexity]
    "src/lib.rs::enumerate_identities" = 20

Each check reads and validates only its own table: its limit can be
configured, and the other check's is not known to it.
"""

from __future__ import annotations

import enum
import json
import tomllib
from pathlib import Path, PurePosixPath

#: Where a repository keeps its baseline, relative to its root.
DEFAULT_PATH = 'code-shape-baseline.toml'

#: The table for each check.
FILE_LENGTH = 'file-length'
COMPLEXITY = 'complexity'
TABLES = (FILE_LENGTH, COMPLEXITY)

#: Separates a file from a function name in a complexity key.
FUNCTION_SEPARATOR = '::'


class BaselineError(Exception):
    """The baseline cannot be used as written."""


class Verdict(enum.Enum):
    """How a measurement compares with its limit and baseline entry."""

    #: Not listed, and within the limit.
    WITHIN = 'within'
    #: Not listed, and over the limit.
    OVER = 'over'
    #: Listed, and exactly at its entry.
    LISTED = 'listed'
    #: Listed, and bigger than its entry.
    GREW = 'grew'
    #: Listed, still over the limit, and smaller than its entry.
    SHRANK = 'shrank'
    #: Listed, and now within the limit.
    CLEARED = 'cleared'

    @property
    def fails(self) -> bool:
        """Whether this verdict fails the hook."""
        return self in _FAILING


_FAILING = frozenset(
    {Verdict.OVER, Verdict.GREW, Verdict.SHRANK, Verdict.CLEARED}
)


def judge(current: int, entry: int | None, limit: int) -> Verdict:
    """
    Compare a measurement with its limit and baseline entry.

    :param current: The size now (lines, or complexity).
    :param entry: Its baseline entry, or ``None`` if it is not listed.
    :param limit: The largest size allowed.
    :returns: The verdict.
    """
    if entry is None:
        return Verdict.OVER if current > limit else Verdict.WITHIN
    if current > entry:
        return Verdict.GREW
    if current <= limit:
        return Verdict.CLEARED
    if current < entry:
        return Verdict.SHRANK
    return Verdict.LISTED


def load(path: Path, table: str, limit: int) -> dict[str, int]:
    """
    Read one table of a baseline file; a missing file is empty.

    :param path: The file.
    :param table: :data:`FILE_LENGTH` or :data:`COMPLEXITY`.
    :param limit: That check's limit, which every entry exceeds.
    :returns: Key to size.
    :raises BaselineError: If the file cannot be read or is malformed;
        the message names the file.
    """
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineError(f'{path}: cannot be read: {exc}') from exc
    try:
        return parse(text, table, limit)
    except BaselineError as exc:
        raise BaselineError(f'{path}: {exc}') from exc


def parse(text: str, table: str, limit: int) -> dict[str, int]:
    """
    Parse one table of baseline text.

    :param text: The TOML.
    :param table: :data:`FILE_LENGTH` or :data:`COMPLEXITY`.
    :param limit: That check's limit, which every entry exceeds.
    :returns: Key to size.
    :raises BaselineError: If it is not TOML, has an unknown table, or
        an entry of *table* is malformed or within *limit*.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise BaselineError(f'not valid TOML: {exc}') from exc
    unknown = sorted(set(data) - set(TABLES))
    if unknown:
        raise BaselineError(
            f'unknown table(s) {", ".join(unknown)}; only '
            f'[{FILE_LENGTH}] and [{COMPLEXITY}] are read'
        )
    raw = data.get(table, {})
    if not isinstance(raw, dict):
        raise BaselineError(f'[{table}] must be a table of entries')
    entries: dict[str, int] = {}
    for key, value in raw.items():
        name = _key(table, str(key))
        if name in entries:
            raise BaselineError(f'[{table}] lists {name!r} twice')
        entries[name] = _size(table, key, value, limit)
    return entries


def normalize(path: str) -> str:
    """
    A repository path in the form baseline keys use.

    :param path: A relative path, e.g. ``"./src/a.py"``.
    :returns: It with ``/`` separators and no leading ``./``.
    :raises BaselineError: If it is empty, absolute, or climbs out of
        the repository with ``..``.
    """
    pure = PurePosixPath(path.replace('\\', '/'))
    if not path or pure.is_absolute() or '..' in pure.parts:
        raise BaselineError(
            f'{path!r} is not a path inside the repository'
        )
    return pure.as_posix()


def function_key(path: str, function: str) -> str:
    """
    The complexity key for a function.

    :param path: Its file, as :func:`normalize` returns it.
    :param function: Its name.
    :returns: ``path::function``.
    """
    return f'{path}{FUNCTION_SEPARATOR}{function}'


def key_path(key: str) -> str:
    """
    The file a baseline key names.

    :param key: A file-length or complexity key.
    :returns: The path before any ``::``.
    """
    return key.partition(FUNCTION_SEPARATOR)[0]


def entry_line(key: str, value: int) -> str:
    """
    One baseline entry as a TOML line.

    :param key: The path, or ``path::function``.
    :param value: Its size.
    :returns: e.g. ``"src/a.py" = 1480``.
    """
    return f'{json.dumps(key)} = {value}'


def render_table(table: str, entries: dict[str, int]) -> str:
    """
    A baseline table with its entries, sorted by key.

    :param table: :data:`FILE_LENGTH` or :data:`COMPLEXITY`.
    :param entries: Key to size.
    :returns: The TOML, ending with a newline.
    """
    lines = [f'[{table}]']
    lines += [entry_line(key, entries[key]) for key in sorted(entries)]
    return '\n'.join(lines) + '\n'


def _key(table: str, key: str) -> str:
    if table == FILE_LENGTH:
        return normalize(key)
    path, separator, function = key.partition(FUNCTION_SEPARATOR)
    if not separator or not function:
        raise BaselineError(
            f'[{table}] {key!r} must be "path::function"'
        )
    return function_key(normalize(path), function)


def _size(table: str, key: str, value: object, limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BaselineError(
            f'[{table}] {key!r} must be a whole number, not {value!r}'
        )
    if value <= limit:
        raise BaselineError(
            f'[{table}] {key!r} = {value} is within the limit of {limit}; '
            f'remove the entry'
        )
    return value
