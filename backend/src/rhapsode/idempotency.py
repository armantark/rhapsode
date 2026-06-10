import json
from typing import Any, cast

from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import StreamingResponse

from rhapsode import models

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in MUTATION_METHODS or not request.url.path.startswith("/api/v1"):
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency-Key header is required for mutations."},
            )
        session_factory = request.app.state.session_factory
        with session_factory() as db:
            record = db.scalar(
                select(models.IdempotencyRecord).where(
                    models.IdempotencyRecord.key == key,
                    models.IdempotencyRecord.method == request.method,
                    models.IdempotencyRecord.path == request.url.path,
                )
            )
            if record is not None:
                return JSONResponse(
                    status_code=record.status_code,
                    content=record.response_json,
                    headers={"Idempotency-Replayed": "true"},
                )
        response = cast(StreamingResponse, await call_next(request))
        chunks = [
            chunk.encode() if isinstance(chunk, str) else bytes(chunk)
            async for chunk in response.body_iterator
        ]
        body = b"".join(chunks)
        content: Any
        try:
            content = json.loads(body) if body else None
        except json.JSONDecodeError:
            content = {"detail": "Non-JSON mutation response was not replayable."}
        if response.status_code < 500:
            with session_factory() as db:
                db.add(
                    models.IdempotencyRecord(
                        key=key,
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        response_json=content,
                    )
                )
                db.commit()
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
