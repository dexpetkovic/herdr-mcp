import pytest
from conftest import TOKEN
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from herdr_mcp.auth import BearerTokenMiddleware


@pytest.fixture
def client() -> TestClient:
    stub = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"))])
    return TestClient(BearerTokenMiddleware(stub, TOKEN))


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/mcp", {}),
        ("/mcp", {"Authorization": f"Bearer {'x' * 32}"}),
        (f"/mcp?token={TOKEN}", {}),
    ],
    ids=["missing header", "wrong token", "token query"],
)
def test_request_without_the_bearer_token_is_rejected(client, path, headers):
    response = client.get(path, headers=headers)

    assert (response.status_code, response.content) == (401, b"")


def test_request_with_the_bearer_token_reaches_the_app(client):
    response = client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert (response.status_code, response.text) == (200, "ok")
