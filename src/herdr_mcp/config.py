"""Server settings read from environment variables at startup."""

import ipaddress
import os
import re
import shutil
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,256}")
HOSTNAME_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME_PATTERN = re.compile(rf"{HOSTNAME_LABEL}(?:\.{HOSTNAME_LABEL})*")


class ConfigError(Exception):
    """A setting is missing or breaks its rule. The message names the variable."""


@dataclass(frozen=True)
class Settings:
    token: str
    public_host: str | None
    host: str
    port: int
    herdr_binary: str
    log_headers: bool


def load_settings() -> Settings:
    return Settings(
        token=_parse_token(os.environ.get("HERDR_MCP_TOKEN")),
        public_host=_parse_public_host(os.environ.get("HERDR_MCP_PUBLIC_HOST")),
        host=_parse_bind_host(os.environ.get("HERDR_MCP_HOST", "127.0.0.1")),
        port=_parse_port(os.environ.get("HERDR_MCP_PORT", "8000")),
        herdr_binary=_resolve_herdr_binary(os.environ.get("HERDR_BIN", "herdr")),
        log_headers=_parse_log_headers(os.environ.get("HERDR_MCP_LOG_HEADERS", "0")),
    )


def _parse_token(value: str | None) -> str:
    if value is None:
        raise ConfigError("HERDR_MCP_TOKEN is required.")
    if not TOKEN_PATTERN.fullmatch(value):
        raise ConfigError(
            "HERDR_MCP_TOKEN must be 32 to 256 characters from A-Z, a-z, 0-9, - and _."
        )
    return value


def _parse_public_host(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) > 253 or not HOSTNAME_PATTERN.fullmatch(value):
        raise ConfigError(
            "HERDR_MCP_PUBLIC_HOST must be a hostname without a scheme, port or path."
        )
    return value


def _parse_bind_host(value: str) -> str:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ConfigError("HERDR_MCP_HOST must be an IP address.") from None
    return value


def _parse_port(value: str) -> int:
    digits = value.lstrip("0")
    port = int(digits) if re.fullmatch(r"[0-9]+", value) and 0 < len(digits) <= 5 else 0
    if not 1 <= port <= 65535:
        raise ConfigError("HERDR_MCP_PORT must be an integer from 1 to 65535.")
    return port


def _resolve_herdr_binary(value: str) -> str:
    resolved = shutil.which(value)
    if resolved is None:
        raise ConfigError("HERDR_BIN must name an executable on the path.")
    return resolved


def _parse_log_headers(value: str) -> bool:
    if value not in ("0", "1"):
        raise ConfigError("HERDR_MCP_LOG_HEADERS must be 0 or 1.")
    return value == "1"
