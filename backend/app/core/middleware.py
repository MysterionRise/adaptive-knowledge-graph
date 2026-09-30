"""
Request ID middleware for log correlation and tracing.
"""

import re
import uuid
from time import perf_counter

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# A client-supplied ID is written to the logs and echoed in a response header, so only
# short token-like values are accepted; anything else gets a fresh UUID.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _request_id_for(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    return supplied if _VALID_REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for tracing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _request_id_for(request)
        request.state.request_id = request_id
        start = perf_counter()

        with logger.contextualize(request_id=request_id):
            logger.info("{} {}", request.method, request.url.path)
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
