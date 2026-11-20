"""The herdr MCP server, its tools and the `herdr-mcp` entry point."""

import json
import logging
import re
import time
from typing import Annotated

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from herdr_mcp.auth import BearerTokenMiddleware
from herdr_mcp.config import ConfigError, Settings, load_settings
from herdr_mcp.herdr import AgentRecord, Herdr, HerdrError, subprocess_runner

logger = logging.getLogger("herdr_mcp")

LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
MAX_TARGET_LENGTH = 64
MAX_SCREEN_CHARACTERS = 4000

SERVER_INSTRUCTIONS = (
    "This server reports the user's own herdr coding agents, live from the user's server. "
    "Call list_agents to learn what the agents are doing and which ones need attention. "
    "Call get_agent_activity with a name or pane id from list_agents "
    "to read what one agent is doing right now. "
    "Keep answers short enough to speak aloud. "
    "Answer from these tools and do not search the web for herdr-mcp."
)


class AgentSummary(BaseModel):
    target: str
    kind: str
    status: str
    workspace: str


class AgentList(BaseModel):
    agents: list[AgentSummary]


class AgentActivity(BaseModel):
    target: str
    screen: str


def summarise_agents(records: list[AgentRecord]) -> list[AgentSummary]:
    return [
        AgentSummary(
            target=record.name or record.pane_id,
            kind=record.kind if record.kind is not None else "unknown",
            status=record.status,
            workspace=record.workspace_label if record.workspace_label is not None else "unknown",
        )
        for record in records
    ]


def trim_screen_text(screen: str) -> str:
    lines = "\n".join(line.rstrip() for line in screen.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", lines).strip("\n")
    return text[-MAX_SCREEN_CHARACTERS:] if text else "The screen is empty."


def build_app(settings: Settings, herdr: Herdr) -> ASGIApp:
    server = MCPServer(name="herdr", instructions=SERVER_INSTRUCTIONS)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def list_agents() -> Annotated[CallToolResult, AgentList]:
        """List herdr agents with their target, kind, status and workspace."""
        started = time.monotonic()
        outcome = "error"
        try:
            result = AgentList(agents=summarise_agents(herdr.snapshot()))
            outcome = "ok"
            return result
        except HerdrError as error:
            _log_herdr_error(error)
            return _spoken_error(error)
        finally:
            _log_tool_call("list_agents", outcome, started)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def get_agent_activity(agent: str) -> Annotated[CallToolResult, AgentActivity]:
        """Read what one local herdr agent's screen shows now. `agent` is a name or pane id from
        list_agents. Tell the user when the screen does not show the agent's task."""
        started = time.monotonic()
        outcome = "error"
        try:
            if not _is_agent_target(agent):
                return _error_result("That is not an agent name or pane id.")
            result = AgentActivity(target=agent, screen=trim_screen_text(herdr.read_screen(agent)))
            outcome = "ok"
            return result
        except HerdrError as error:
            if error.code == "agent_not_found":
                return _error_result("No running agent matches that target.")
            _log_herdr_error(error)
            return _spoken_error(error)
        finally:
            _log_tool_call("get_agent_activity", outcome, started)

    app: ASGIApp = server.streamable_http_app(
        json_response=True, transport_security=_transport_security(settings.public_host)
    )
    app = BearerTokenMiddleware(app, settings.token)
    if settings.log_headers:
        app = HeaderNameLogger(app)
    return app


def _transport_security(public_host: str | None) -> TransportSecuritySettings:
    hosts = list(LOOPBACK_HOSTS)
    origins = list(LOOPBACK_ORIGINS)
    if public_host is not None:
        hosts.append(public_host)
        origins.append(f"https://{public_host}")
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def _log_herdr_error(error: HerdrError) -> None:
    logger.warning(
        "herdr call failed",
        extra={
            "herdr_code": error.code,
            "herdr_command": error.command,
            "herdr_exit_code": error.exit_code,
            "herdr_field": error.field,
            "herdr_cause": repr(error.__cause__) if error.__cause__ is not None else None,
        },
    )


def _log_tool_call(tool: str, outcome: str, started: float) -> None:
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info("tool call", extra={"tool": tool, "outcome": outcome, "duration_ms": duration_ms})


def _is_agent_target(value: str) -> bool:
    """herdr parses a leading `-` as an option, and `--` cannot protect an agent target."""
    return 0 < len(value) <= MAX_TARGET_LENGTH and not value.startswith("-") and "\0" not in value


def _spoken_error(error: HerdrError) -> CallToolResult:
    if error.code == "server_not_running":
        return _error_result("herdr is not running on the server.")
    return _error_result("herdr could not answer the request.")


def _error_result(sentence: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=sentence)], is_error=True)


class HeaderNameLogger:
    """Logs the header names of each HTTP request. Header values can hold the token."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            names = sorted({name.decode("latin-1") for name, _ in scope["headers"]})
            logger.info("request headers", extra={"path": scope["path"], "header_names": names})
        await self._app(scope, receive, send)


class FieldsFormatter(logging.Formatter):
    STANDARD_ATTRIBUTES = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.STANDARD_ATTRIBUTES
        }
        text = super().format(record)
        return f"{text} {json.dumps(fields, default=str)}" if fields else text


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as error:
        raise SystemExit(f"herdr-mcp: {error}") from None
    handler = logging.StreamHandler()
    handler.setFormatter(FieldsFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    app = build_app(settings, Herdr(settings.herdr_binary, subprocess_runner))
    uvicorn.run(app, host=settings.host, port=settings.port)
