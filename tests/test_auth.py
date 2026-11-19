import pytest
from conftest import TOKEN


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/mcp", {}),
        ("/mcp", {"Authorization": f"Bearer {'x' * 32}"}),
        (f"/mcp?token={TOKEN}", {}),
    ],
    ids=["missing header", "wrong token", "token query"],
)
def test_request_without_the_bearer_token_is_rejected(auth_client, path, headers):
    response = auth_client.get(path, headers=headers)

    assert (response.status_code, response.content) == (401, b"")


def test_request_with_the_bearer_token_reaches_the_app(auth_client):
    response = auth_client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert (response.status_code, response.text) == (200, "ok")
