"""The error type of the herdr connector."""


class HerdrError(Exception):
    """A herdr call failed. `field` is the dotted path of malformed response data, when known."""

    def __init__(
        self, code: str, command: str, exit_code: int | None, field: str | None = None
    ) -> None:
        super().__init__(f"herdr {command} failed with {code} (exit code {exit_code})")
        self.code = code
        self.command = command
        self.exit_code = exit_code
        self.field = field
