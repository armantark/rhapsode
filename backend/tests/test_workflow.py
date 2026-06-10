from collections.abc import Callable

from fastapi.testclient import TestClient

from rhapsode.app import create_app


def test_end_to_end_recall_and_restart_recovery(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    created = client.post(
        "/api/v1/sessions",
        json={
            "revision_id": revision["id"],
            "modes": ["progressive_fading", "full_passage"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    assert len(session["items"]) == 3

    with TestClient(create_app(session_factory)) as restarted:  # type: ignore[arg-type]
        resumed = restarted.get(f"/api/v1/sessions/{session['id']}")
        assert resumed.status_code == 200
        assert resumed.json()["current_index"] == 0

        first_item = resumed.json()["items"][0]
        attempted = restarted.post(
            f"/api/v1/sessions/{session['id']}/attempts",
            json={"item_id": first_item["id"], "rating": "hesitant", "latency_ms": 1800},
            headers=mutation(),
        )
        assert attempted.status_code == 201, attempted.text
        result = attempted.json()
        assert result["session"]["current_index"] == 1
        assert result["mastery_stage"] == "learning"
        assert result["due_at"]

        due = restarted.get("/api/v1/analytics/due").json()
        assert isinstance(due, list)
        weak = restarted.get(f"/api/v1/analytics/weak-links?revision_id={revision['id']}").json()
        assert weak[0]["difficulty_rate"] == 0


def test_incorrect_attempt_becomes_weak_link(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"]},
        headers=mutation(),
    ).json()
    first = session["items"][0]
    client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "revealed"},
        headers=mutation(),
    )
    weak = client.get(f"/api/v1/analytics/weak-links?revision_id={revision['id']}").json()
    assert weak[0]["segment_id"] == first["segment_id"]
    assert weak[0]["difficulty_rate"] == 1


def test_reference_media_round_trip(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
    monkeypatch: object,
    tmp_path: object,
) -> None:
    from rhapsode.api import router
    from rhapsode.config import Settings

    settings = Settings(
        data_dir=tmp_path,
        media_dir=tmp_path / "media",
        backup_dir=tmp_path / "backups",
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
    )
    settings.ensure_directories()
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    revision = passage["active_revision"]
    uploaded = client.post(
        "/api/v1/media",
        data={"category": "reference", "revision_id": revision["id"]},
        files={"upload": ("iliad.m4a", b"reference-audio", "audio/mp4")},
        headers=mutation(),
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    content = client.get(f"/api/v1/media/{asset['id']}/content")
    assert content.content == b"reference-audio"
    assert client.delete(f"/api/v1/media/{asset['id']}", headers=mutation()).json() == {
        "deleted": True
    }


def test_media_rejects_non_audio(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
) -> None:
    response = client.post(
        "/api/v1/media",
        data={"category": "reference"},
        files={"upload": ("notes.txt", b"not audio", "text/plain")},
        headers=mutation(),
    )
    assert response.status_code == 422
