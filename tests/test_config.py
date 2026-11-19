import sys

import pytest
from conftest import TOKEN

from herdr_mcp.config import ConfigError, load_settings

SETTING_VARIABLES = [
    "HERDR_MCP_TOKEN",
    "HERDR_MCP_PUBLIC_HOST",
    "HERDR_MCP_HOST",
    "HERDR_MCP_PORT",
    "HERDR_BIN",
    "HERDR_MCP_LOG_HEADERS",
]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("HERDR_MCP_TOKEN", None),
        ("HERDR_MCP_TOKEN", "t" * 31),
        ("HERDR_MCP_TOKEN", "t" * 16 + " " + "t" * 16),
        ("HERDR_MCP_PUBLIC_HOST", "mcp.example.com:443"),
        ("HERDR_MCP_HOST", "localhost:80"),
        ("HERDR_MCP_PORT", "0"),
    ],
)
def test_invalid_setting_names_its_variable(monkeypatch, variable, value):
    for name in SETTING_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERDR_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("HERDR_BIN", sys.executable)
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)

    with pytest.raises(ConfigError) as raised:
        load_settings()

    assert str(raised.value).startswith(f"{variable} ")
