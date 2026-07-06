"""
Request ID middleware for log correlation and tracing.
"""

import uuid
from time import perf_counter

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for tracing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = perf_counter()

        with logger.contextualize(request_id=request_id):
            logger.info(f"{request.method} {request.url.path}")
            response = await call_next(request)

        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        logger.info(
            "request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = str(elapsed_ms)
        return response
