# Working in code-shape-hooks

## Code shape

- Keep every code and test file under 1,000 lines, and aim for 300-350.
  Split by responsibility before a file reaches that, not after.
- Keep every function at McCabe complexity 10 or below.
- One responsibility per module. Several files for one responsibility go
  in one package, whose `__init__.py` holds only a docstring; import
  from the defining module.

## Conventions

- Standard library only, apart from lizard and its two dependencies,
  which are pinned exactly in `pyproject.toml` (pre-commit installs a
  hook's dependencies without a lock file).
- Strict typing: `mypy --strict` passes. lizard has no types, so
  `stubs/lizard.pyi` declares the part of its API in use.
- Never suppress a finding (`noqa`, `type: ignore`); change the code so
  the rule no longer matches.
- Tests come first, use `unittest`, and pass with warnings as errors.

## Commands

```sh
uv sync --locked   # first, and after editing pyproject.toml
PYTHONWARNINGS=error uv run --locked --no-sync -m unittest discover -s tests
uvx ruff@0.17.4 check .
uv sync --locked && uvx mypy@2.4.1 --python-executable .venv/bin/python
uvx pre-commit@4.7.0 validate-manifest .pre-commit-hooks.yaml
```
