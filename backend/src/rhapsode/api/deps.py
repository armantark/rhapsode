from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Generator[Session]:
    with request.app.state.session_factory() as session:
        yield session
