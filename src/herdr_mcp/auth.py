"""ASGI middleware that admits only requests carrying the configured bearer token."""

import hmac

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or self._is_authorized(scope):
            await self._app(scope, receive, send)
        elif scope["type"] == "http":
            await Response(status_code=401)(scope, receive, send)
        else:
            await WebSocketClose()(scope, receive, send)

    def _is_authorized(self, scope: Scope) -> bool:
        provided = next(
            (value for name, value in scope["headers"] if name == b"authorization"), b""
        )
        return hmac.compare_digest(provided, self._expected)
