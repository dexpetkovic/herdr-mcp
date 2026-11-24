# herdr-mcp

herdr-mcp is an MCP server that reports herdr agents through the herdr CLI.

## Commands

- `uv sync` installs the package and its dev dependencies.
- `uv run pytest` runs the tests.
- `uv run ruff check` runs the linter.
- `uv run ruff format --check` checks the formatting.

All three checks must pass before a pull request opens.

## Rules

- The `src/herdr_mcp/herdr/` package is the herdr connector. `client.py` is the only module that starts a subprocess. `validator.py` is the only module that decodes herdr's JSON.
- Tests never run the real herdr binary. They pass a fake runner from `tests/conftest.py` to `Herdr`.
- Synthetic fixtures in `tests/conftest.py` preserve the fields the server reads from herdr 0.9.5.
- The global quality gates in `~/.claude/skills/implement-ticket/quality-gates.md` apply.
