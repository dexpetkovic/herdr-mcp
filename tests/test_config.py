import sys

import pytest
from conftest import INVALID_SETTINGS, SETTING_VARIABLES, TOKEN

from herdr_mcp.config import ConfigError, load_settings


@pytest.mark.parametrize(("variable", "value"), INVALID_SETTINGS)
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


def test_port_defaults_to_8765(monkeypatch):
    for name in SETTING_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERDR_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("HERDR_BIN", sys.executable)

    port = load_settings().port

    assert port == 8765
