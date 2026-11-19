"""The herdr MCP server, its tools and the `herdr-mcp` entry point."""

import json
import logging

import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from herdr_mcp.auth import BearerTokenMiddleware
from herdr_mcp.config import ConfigError, Settings, load_settings
from herdr_mcp.herdr import AgentRecord, Herdr, HerdrError, subprocess_runner

logger = logging.getLogger("herdr_mcp")

LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


class AgentSummary(BaseModel):
    target: str
    kind: str
    status: str
    workspace: str


class AgentList(BaseModel):
    agents: list[AgentSummary]


def summarise_agents(records: list[AgentRecord]) -> list[AgentSummary]:
    return [
        AgentSummary(
            target=record.name or record.pane_id,
            kind=record.kind,
            status=record.status,
            workspace=record.workspace_label or "unknown",
        )
        for record in records
    ]


def build_app(settings: Settings, herdr: Herdr) -> ASGIApp:
    server = MCPServer(name="herdr")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def list_agents() -> AgentList:
        """List the herdr agents with their name, kind, status and workspace."""
        try:
            records = herdr.snapshot()
        except HerdrError as error:
            _log_herdr_error(error)
            raise ToolError(_spoken_error(error)) from None
        return AgentList(agents=summarise_agents(records))

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
        },
    )


def _spoken_error(error: HerdrError) -> str:
    if error.code == "server_not_running":
        return "herdr is not running on the server."
    return "herdr could not answer the request."


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
    """Appends a record's structured `extra` fields to the message as JSON."""

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
