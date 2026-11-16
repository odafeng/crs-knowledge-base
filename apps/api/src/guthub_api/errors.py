"""Request IDs and the contract's single error shape: {"error": {"code", "message", "requestId"}}."""

import logging
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("guthub_api")

REQUEST_ID_HEADER = "X-Request-ID"

# Codes are limited to the contract's Error.code enum.
CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


class RequestIdMiddleware:
    """Assigns a server-generated ID to every request. Client-supplied IDs are ignored so they cannot forge log lines."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_id)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or uuid4().hex


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        {"error": {"code": code, "message": message, "requestId": request_id}},
        status_code=status,
        # Set here too: unhandled errors are answered outside RequestIdMiddleware.
        headers={"Cache-Control": "no-store", REQUEST_ID_HEADER: request_id},
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    status = exc.status_code
    code = CODES.get(status, "validation_error" if status < 500 else "unavailable")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(status).phrase
    return error_response(request, status, code, message)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 422, "validation_error", "Invalid request parameters")


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"request_id": _request_id(request)})
    return error_response(request, 500, "unavailable", "Internal error")


def install_error_handling(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
