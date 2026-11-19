# herdr-mcp

herdr-mcp is an MCP server that reports and steers herdr agents through the herdr CLI.

## Commands

- `uv sync` installs the package and its dev dependencies.
- `uv run pytest` runs the tests.
- `uv run ruff check` runs the linter.
- `uv run ruff format --check` checks the formatting.

All three checks must pass before a pull request opens.

## Rules

- `src/herdr_mcp/herdr.py` is the only module that starts a subprocess or reads herdr's JSON.
- Tests never run the real herdr binary. They pass a fake runner from `tests/conftest.py` to `Herdr`.
- Test data in `tests/conftest.py` keeps herdr 0.9.5's wire shape and uses synthetic values only.
- The global quality gates in `~/.claude/skills/implement-ticket/quality-gates.md` apply.
