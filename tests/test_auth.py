import pytest
from conftest import TOKEN, UNAUTHORIZED_REQUESTS


@pytest.mark.parametrize(
    ("path", "headers"),
    UNAUTHORIZED_REQUESTS.values(),
    ids=UNAUTHORIZED_REQUESTS.keys(),
)
def test_request_without_the_bearer_token_is_rejected(auth_client, path, headers):
    response = auth_client.get(path, headers=headers)

    assert (response.status_code, response.content) == (401, b"")


def test_request_with_the_bearer_token_reaches_the_app(auth_client):
    response = auth_client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert (response.status_code, response.text) == (200, "ok")
