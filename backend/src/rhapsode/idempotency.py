import asyncio
import json
from typing import Any, cast

from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import StreamingResponse

from rhapsode import models

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# A reservation row marks a request as in flight. It is claimed BEFORE the
# endpoint runs: without that, two requests sharing a key (a client retry
# racing its original) both pass the "no record" lookup and both EXECUTE the
# mutation — the observed symptom was duplicate passages from a single create.
PENDING_STATUS = 0
# The loser polls briefly for the winner's stored response; a mutation on this
# local app resolves in well under this.
REPLAY_WAIT_SECONDS = 10.0
REPLAY_POLL_SECONDS = 0.1


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

        def lookup() -> tuple[int, Any] | None:
            with session_factory() as db:
                record = db.scalar(
                    select(models.IdempotencyRecord).where(
                        models.IdempotencyRecord.key == key,
                        models.IdempotencyRecord.method == request.method,
                        models.IdempotencyRecord.path == request.url.path,
                    )
                )
                if record is None:
                    return None
                return (record.status_code, record.response_json)

        async def await_replay() -> Response:
            waited = 0.0
            while waited < REPLAY_WAIT_SECONDS:
                found = lookup()
                if found is None:
                    # The winner failed hard and released its reservation;
                    # this retry may proceed as a fresh attempt.
                    return await self._reserve_and_run(request, call_next, key)
                status_code, body = found
                if status_code != PENDING_STATUS:
                    return JSONResponse(
                        status_code=status_code,
                        content=body,
                        headers={"Idempotency-Replayed": "true"},
                    )
                await asyncio.sleep(REPLAY_POLL_SECONDS)
                waited += REPLAY_POLL_SECONDS
            return JSONResponse(
                status_code=409,
                content={"detail": "This request is still being processed."},
            )

        existing = lookup()
        if existing is not None:
            status_code, body = existing
            if status_code == PENDING_STATUS:
                return await await_replay()
            return JSONResponse(
                status_code=status_code,
                content=body,
                headers={"Idempotency-Replayed": "true"},
            )
        return await self._reserve_and_run(request, call_next, key)

    async def _reserve_and_run(
        self, request: Request, call_next: RequestResponseEndpoint, key: str
    ) -> Response:
        session_factory = request.app.state.session_factory
        with session_factory() as db:
            db.add(
                models.IdempotencyRecord(
                    key=key,
                    method=request.method,
                    path=request.url.path,
                    status_code=PENDING_STATUS,
                    response_json={"detail": "pending"},
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # A concurrent request claimed the key first — adopt its
                # outcome instead of executing the mutation a second time.
                return await self._replay_after_loss(request, call_next, key)

        try:
            response = cast(StreamingResponse, await call_next(request))
        except Exception:
            self._release(request, key)
            raise
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
                db.execute(
                    update(models.IdempotencyRecord)
                    .where(
                        models.IdempotencyRecord.key == key,
                        models.IdempotencyRecord.method == request.method,
                        models.IdempotencyRecord.path == request.url.path,
                    )
                    .values(status_code=response.status_code, response_json=content)
                )
                db.commit()
        else:
            # Server errors are not replayable; release the key so an honest
            # retry can try again.
            self._release(request, key)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    async def _replay_after_loss(
        self, request: Request, call_next: RequestResponseEndpoint, key: str
    ) -> Response:
        session_factory = request.app.state.session_factory
        waited = 0.0
        while waited < REPLAY_WAIT_SECONDS:
            with session_factory() as db:
                record = db.scalar(
                    select(models.IdempotencyRecord).where(
                        models.IdempotencyRecord.key == key,
                        models.IdempotencyRecord.method == request.method,
                        models.IdempotencyRecord.path == request.url.path,
                    )
                )
                if record is None:
                    return await self._reserve_and_run(request, call_next, key)
                if record.status_code != PENDING_STATUS:
                    return JSONResponse(
                        status_code=record.status_code,
                        content=record.response_json,
                        headers={"Idempotency-Replayed": "true"},
                    )
            await asyncio.sleep(REPLAY_POLL_SECONDS)
            waited += REPLAY_POLL_SECONDS
        return JSONResponse(
            status_code=409,
            content={"detail": "This request is still being processed."},
        )

    def _release(self, request: Request, key: str) -> None:
        session_factory = request.app.state.session_factory
        with session_factory() as db:
            db.execute(
                delete(models.IdempotencyRecord).where(
                    models.IdempotencyRecord.key == key,
                    models.IdempotencyRecord.method == request.method,
                    models.IdempotencyRecord.path == request.url.path,
                    models.IdempotencyRecord.status_code == PENDING_STATUS,
                )
            )
            db.commit()
