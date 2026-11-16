# code-shape-hooks

[pre-commit](https://pre-commit.com) hooks that keep code readable for
people and coding agents alike:

| Hook | Fails | Notes (passes) |
| --- | --- | --- |
| `check-file-length` | a code or test file over 1,000 lines | one over 350 lines |
| `check-complexity` | a function over McCabe complexity 10 | |
| `check-baseline-ratchet` | a baseline entry raised or added | |

A file that keeps growing usually holds more than one responsibility, and
a long file is hard to read whole. The hard limit stops that; the note at
350 lines asks for a split before it is needed.

`check-complexity` measures with [lizard](https://github.com/terryyin/lizard)
and is meant for languages without a linter that enforces complexity,
such as Rust. Python projects should use ruff's `C901` with
`max-complexity = 10` instead.

## Use

```yaml
repos:
  - repo: https://github.com/st0w/code-shape-hooks
    rev: v0.2.0
    hooks:
      - id: check-file-length
      - id: check-complexity    # Rust; leave out where a linter does it
      - id: check-baseline-ratchet
```

Both hooks take their limits as arguments, and the file types they check
can be changed with `types_or`:

```yaml
      - id: check-file-length
        args: [--max-lines, '800', --target-lines, '300']
      - id: check-complexity
        args: [--max-complexity, '12']
```

Markdown, YAML, lock files and other data are not code and are not
checked by default.

Run the hooks in CI too, since a local hook can be skipped or not
installed. There, tell `check-baseline-ratchet` which revision to
compare with (see below):

```yaml
      - uses: actions/checkout@<sha>  # vN
        with:
          fetch-depth: 2
      - run: SKIP=no-commit-to-branch pre-commit run --all-files
        env:
          CODE_SHAPE_BASE_REF: HEAD^1
```

## The baseline: adopting the limits in an existing repository

Code already over a limit when the hooks are adopted is listed in
`code-shape-baseline.toml` at the repository root:

```toml
[file-length]
"src/big_module.py" = 1480

[complexity]
"src/lib.rs::enumerate_identities" = 20
```

A listed file or function may shrink but never grow:

- **Grew past its entry:** fails.
- **Shrank but is still over the limit:** fails until its entry is lowered
  to the new size. The message gives the exact line to write. This locks
  in the progress, so a later change cannot quietly regrow it.
- **Within the limit now:** fails until its entry is removed.
- **No longer exists:** fails until its entry is removed. This is checked
  on every run, because a deleted file is never passed to a hook.

### The baseline cannot be raised

The entries are only text, so on their own they rely on nobody, person
or agent, raising one or listing a new file to get a change through.
`check-baseline-ratchet` closes that: it compares the baseline with its
version at a base revision and fails if an entry was raised or added.
Lowering and removing entries pass.

- **Locally** the base is `HEAD`, so each commit is checked against its
  parent.
- **In CI** set `CODE_SHAPE_BASE_REF` to compare a pull request as a
  whole. On GitHub, a `pull_request` run checks out a merge commit whose
  first parent is the target branch, so `HEAD^1` with `fetch-depth: 2`
  is that branch; on a push, it is the commit before. `--base-ref`
  overrides both.
- **A moved file or renamed function** changes its key. The new entry
  passes if the old one is removed, its file or function is gone from
  the tree, and the new one is no larger. The hook cannot tell a move
  from deleting one file and adding another, but either way the baseline
  lists no more, and nothing larger, than before.
- **Adopting a baseline** passes: there is nothing at the base to
  compare with.

This binds only where the CI job is required to pass before merging
(branch protection), and only while the workflow still runs it: review
changes to the CI workflow and the hook configuration as you would
changes to the baseline.

Functions are keyed `path::name`. Names are not unique within a file (two
`impl` blocks can each have `new`), so all functions sharing a key are
held to its entry.

To write the first baseline, print the entries for everything currently
over the limits, passing only code files:

```sh
uvx --from git+https://github.com/st0w/code-shape-hooks@v0.2.0 \
  check-file-length --print-baseline $(git ls-files '*.py' '*.rs')
uvx --from git+https://github.com/st0w/code-shape-hooks@v0.2.0 \
  check-complexity --print-baseline $(git ls-files '*.rs')
```

## Guidance for coding agents

Projects using these hooks should tell their coding agents the same
rules, in `AGENTS.md` (with a `CLAUDE.md` that holds only `@AGENTS.md`):

- Keep every code and test file under 1,000 lines, and aim for 300-350.
  Split by responsibility before a file reaches that, not after.
- Keep every function at McCabe complexity 10 or below.
- One responsibility per module. Several files for one responsibility go
  in one package, whose `__init__` holds only a docstring; import from
  the defining module.
- Never grow a file or function listed in `code-shape-baseline.toml`.
  When a change shrinks one, lower or remove its entry in the same
  change.

## Develop

```sh
uv sync --locked
PYTHONWARNINGS=error uv run --locked --no-sync -m unittest discover -s tests
uvx ruff@0.17.4 check .
uv sync --locked && uvx mypy@2.4.1 --python-executable .venv/bin/python
```
