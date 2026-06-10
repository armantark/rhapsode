from collections.abc import Callable, Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from rhapsode.app import create_app
from rhapsode.database import Base, build_engine


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient]:
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


@pytest.fixture
def mutation() -> Callable[..., dict[str, str]]:
    def headers(key: str | None = None) -> dict[str, str]:
        return {"Idempotency-Key": key or str(uuid4())}

    return headers


@pytest.fixture
def greek_id(client: TestClient) -> str:
    languages = client.get("/api/v1/languages").json()
    return next(language["id"] for language in languages if language["slug"] == "ancient-greek")


@pytest.fixture
def greek_passage_payload(greek_id: str) -> dict[str, object]:
    return {
        "title": "Iliad 1.1-2",
        "language_profile_id": greek_id,
        "description": "Opening invocation",
        "source_text": (
            "μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος\nοὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε"
        ),
        "segments": [
            {
                "client_id": "line-1",
                "kind": "line",
                "ordinal": 0,
                "text": "μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος",
                "cue": "Sing, goddess",
                "annotations": [
                    {"layer": "translation", "value": "Sing, goddess, the anger of Achilles"}
                ],
            },
            {
                "client_id": "line-2",
                "kind": "line",
                "ordinal": 1,
                "text": "οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε",
                "cue": "destructive",
            },
        ],
    }


@pytest.fixture
def passage(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    greek_passage_payload: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        "/api/v1/passages", json=greek_passage_payload, headers=mutation("create-greek")
    )
    assert response.status_code == 201, response.text
    return response.json()
