"""What a hook found, printed the way pre-commit shows it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from code_shape_hooks import baseline as B

#: Exit status when the hook found something to fix.
EXIT_FINDINGS = 1

#: Exit status when the hook could not run as configured.
EXIT_UNUSABLE = 2


@dataclass
class Report:
    """
    A hook run's findings.

    :param errors: What fails the hook, one line each.
    :param notes: What it passes but mentions, one line each.
    """

    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def emit(self) -> int:
        """
        Print the notes, then the errors, on stdout.

        pre-commit shows a passing hook's output only when the hook is
        verbose, so the hooks set ``verbose: true`` for the notes.

        :returns: The exit status: 0, or :data:`EXIT_FINDINGS`.
        """
        for line in self.notes:
            print(f'note: {line}')
        for line in self.errors:
            print(f'error: {line}')
        return EXIT_FINDINGS if self.errors else 0


def load_baseline(
    path: str, table: str, limit: int
) -> dict[str, int] | None:
    """
    Read a hook's baseline table, printing why if it cannot.

    :param path: The baseline file.
    :param table: The hook's table.
    :param limit: The hook's limit.
    :returns: The entries, or ``None`` after printing the problem.
    """
    try:
        return B.load(Path(path), table, limit)
    except B.BaselineError as exc:
        print(f'error: {exc}')
        return None


def missing_files(entries: dict[str, int], baseline_path: str) -> list[str]:
    """
    An error for each entry whose file no longer exists.

    Checked on every run, not only for the files a commit touches: a
    deleted file is never passed to a hook, so its entry would
    otherwise stay forever.

    :param entries: A hook's baseline table.
    :param baseline_path: The baseline file, to name in the message.
    :returns: One line per stale entry.
    """
    return [
        f'{key}: listed in {baseline_path} but no longer exists. '
        f'Remove its entry.'
        for key in sorted(entries)
        if not Path(B.key_path(key)).is_file()
    ]
