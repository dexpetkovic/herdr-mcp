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
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from herdr_mcp.auth import BearerTokenMiddleware
from herdr_mcp.config import ConfigError, Settings, load_settings
from herdr_mcp.herdr import AgentRecord, Herdr, HerdrError, subprocess_runner

logger = logging.getLogger("herdr_mcp")

LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
MAX_TARGET_LENGTH = 64
MAX_SCREEN_CHARACTERS = 4000
MAX_MESSAGE_CHARACTERS = 2000
AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
REVIEWER_NAME = re.compile(r"(?:^|-)rev-")
CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f-\x9f]")
READY_STATUSES = frozenset({"idle", "done"})
REPLY_WAIT_MS = 30000
AGENT_BLOCKED = "That agent is waiting on a dialog, so I did not send the message."
READINESS_UNKNOWN = "I cannot tell whether that agent is ready, so I did not send the message."
MAYBE_SENT = "The message may have been sent. Check the agent's activity before you send it again."
STATUS_REFUSALS = {
    "working": "That agent is busy, so I did not send the message.",
    "blocked": AGENT_BLOCKED,
}
# These prompt errors and `agent_not_found` prove that herdr sent nothing.
PROMPT_REFUSALS = {
    "agent_blocked": AGENT_BLOCKED,
    "agent_not_ready": "That agent is not ready for a message, so I did not send it.",
}

SERVER_INSTRUCTIONS = (
    "This server connects the user to their herdr orchestrator agents, live from the user's "
    "server. "
    "Call list_agents to find the orchestrators. It lists only orchestrators. "
    "Send every question or instruction about the agents to an orchestrator with send_message. "
    "Pass the user's words unchanged. Do not read them back or ask the user to confirm. "
    "To pick the orchestrator, keep the rows in the workspace the user named, if any. "
    "Send only when exactly one remains and its target is a name. "
    "When several remain and the user named no workspace, ask which workspace. "
    "That is the only question you ask. "
    "When several remain in the named workspace, say the orchestrator is ambiguous. "
    "When the one remaining target is a pane id, say the orchestrator has no herdr name. "
    "When none remains, say the list found no orchestrator. "
    "send_message waits for the orchestrator's turn to settle and returns its visible screen. "
    "Summarise screen in a few spoken sentences as what the orchestrator's screen shows. "
    "When the screen does not show an answer to the user's message, say what it does show. "
    "When waiting_on_dialog is true, say the orchestrator is waiting on a dialog. "
    "When sent is true and screen is null, say the message was delivered "
    "and the screen could not be read. "
    "When screen says the screen is empty, say the message was delivered "
    "and the screen is empty. "
    "When the user later asks for the answer, call get_agent_activity with the same target. "
    "After an error that says the message may have been sent, or when the send_message call "
    "itself fails, call get_agent_activity on the same target before any new send. "
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


class SentMessage(BaseModel):
    target: str
    sent: bool
    screen: str | None
    waiting_on_dialog: bool


def summarise_agents(records: list[AgentRecord]) -> list[AgentSummary]:
    return [
        AgentSummary(
            target=record.name or record.pane_id,
            kind=record.kind if record.kind is not None else "unknown",
            status=record.status,
            workspace=record.workspace_label if record.workspace_label is not None else "unknown",
        )
        for record in records
        if is_orchestrator_position(record)
    ]


def is_orchestrator_position(record: AgentRecord) -> bool:
    is_reviewer = record.name is not None and REVIEWER_NAME.search(record.name) is not None
    return (
        record.is_main_checkout is True
        and record.tab_number == 1
        and record.agents_in_tab == 1
        and not is_reviewer
    )


def is_orchestrator(record: AgentRecord) -> bool:
    return bool(record.name) and is_orchestrator_position(record)


def trim_screen_text(screen: str) -> str:
    lines = "\n".join(line.rstrip() for line in screen.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", lines).strip("\n")
    return text[-MAX_SCREEN_CHARACTERS:] if text else "The screen is empty."


def build_app(settings: Settings, herdr: Herdr) -> ASGIApp:
    server = MCPServer(name="herdr", instructions=SERVER_INSTRUCTIONS)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def list_agents() -> Annotated[CallToolResult, AgentList]:
        """List the orchestrators, each alone in tab 1 of its main checkout."""
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

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def send_message(
        agent: str,
        text: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARACTERS)],
    ) -> Annotated[CallToolResult, SentMessage]:
        """Use the orchestrator's herdr name and pass the user's words unchanged.
        The result includes the visible screen when herdr can read it."""
        started = time.monotonic()
        outcome = "error"
        try:
            if ":" in agent:
                return _error_result(
                    "Name the agent instead of its pane. You can name it with herdr agent rename."
                )
            if not AGENT_NAME.fullmatch(agent):
                return _error_result("That is not a valid agent name.")
            if CONTROL_CHARACTER.search(text):
                return _error_result("The message contains a character I cannot send.")
            try:
                records = herdr.snapshot()
            except HerdrError as error:
                _log_herdr_error(error)
                return _spoken_error(error)
            refusal = _orchestrator_refusal(agent, records)
            if refusal is not None:
                return _error_result(refusal)
            try:
                settled_status = herdr.prompt(agent, text, REPLY_WAIT_MS)
            except HerdrError as error:
                _log_herdr_error(error)
                if error.code == "agent_not_found":
                    return _error_result(f"No agent named {agent} is running.")
                return _error_result(PROMPT_REFUSALS.get(error.code, MAYBE_SENT))
            try:
                screen = trim_screen_text(herdr.read_screen(agent))
            except HerdrError as error:
                _log_herdr_error(error)
                screen = None
            outcome = "ok"
            return SentMessage(
                target=agent,
                sent=True,
                screen=screen,
                waiting_on_dialog=settled_status == "blocked",
            )
        finally:
            _log_tool_call("send_message", outcome, started)

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
    """herdr reads a flag such as `--help` in the target position, and `--` cannot protect it."""
    return 0 < len(value) <= MAX_TARGET_LENGTH and not value.startswith("-") and "\0" not in value


def _orchestrator_refusal(name: str, records: list[AgentRecord]) -> str | None:
    record = next((record for record in records if record.name == name), None)
    if record is None:
        return f"No agent named {name} is running."
    if record.agents_in_tab > 1:
        return "That tab has more than one agent, so I did not send the message."
    if not is_orchestrator(record):
        return "I can only send messages to an orchestrator agent."
    if record.status not in READY_STATUSES:
        return STATUS_REFUSALS.get(record.status, READINESS_UNKNOWN)
    return None


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
