"""FastAPI request logging middleware helpers."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response

from .context import request_id_ctx


async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach a request id and log inbound/outbound request details."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request_id_ctx.set(request_id)

    start_time = time.perf_counter()

    client = _client_address(request)
    logging.debug(f'<- {client} - "{request.method} {request.url.path}"')

    response = await call_next(request)

    process_time_ms = (time.perf_counter() - start_time) * 1000
    logging.info(
        f'-> {client} - "{request.method} {request.url.path}" '
        f"{response.status_code} | {process_time_ms:.2f}"
    )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = f"{process_time_ms:.2f}"

    return response


def _client_address(request: Request) -> str:
    client: Any = request.client
    if client is None:
        return "-"
    return f"{client.host}:{client.port}"
