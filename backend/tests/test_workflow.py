from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from rhapsode.app import create_app
from rhapsode.services import prep


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


def test_smart_session_scaffolds_new_segments(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "segment_kinds": ["line"]},
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    assert session["plan"]["smart"] is True
    # Never-practiced segments all get maximum support.
    assert {item["mode"] for item in session["items"]} == {"progressive_fading"}


def test_collection_session_spans_member_passages(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
    greek_passage_payload: dict[str, object],
) -> None:
    second = client.post(
        "/api/v1/passages",
        json={**greek_passage_payload, "title": "Iliad 1.3-4"},
        headers=mutation(),
    ).json()
    collection = client.post(
        "/api/v1/collections", json={"name": "Iliad opening"}, headers=mutation()
    ).json()
    for member in (passage, second):
        added = client.post(
            f"/api/v1/collections/{collection['id']}/members",
            json={"passage_id": member["id"]},
            headers=mutation(),
        )
        assert added.status_code == 200, added.text

    created = client.post(
        "/api/v1/sessions",
        json={
            "collection_id": collection["id"],
            "modes": ["cue_recall"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    first_revision_id = passage["active_revision"]["id"]
    second_revision_id = second["active_revision"]["id"]
    assert session["revision_id"] is None
    assert session["collection_id"] == collection["id"]
    assert session["plan"]["revision_ids"] == [first_revision_id, second_revision_id]
    assert [item["revision_id"] for item in session["items"]] == [
        first_revision_id,
        first_revision_id,
        second_revision_id,
        second_revision_id,
    ]


def test_due_only_session_targets_due_segments(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from rhapsode import models

    revision = passage["active_revision"]
    # Nothing reviewed yet, so a due-only session has no targets.
    empty = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "due_only": True},
        headers=mutation(),
    )
    assert empty.status_code == 422

    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    first = session["items"][0]
    client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "hesitant"},
        headers=mutation(),
    )
    # FSRS schedules the next review in the future; backdate it to simulate
    # the passage of time rather than waiting.
    with session_factory() as db:  # type: ignore[operator]
        db.execute(update(models.ReviewState).values(due_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()

    due_session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "due_only": True, "segment_kinds": ["line"]},
        headers=mutation(),
    )
    assert due_session.status_code == 201, due_session.text
    body = due_session.json()
    assert body["plan"]["due_only"] is True
    # Only the single graded-and-now-due segment is in the plan; its stage is
    # "learning", so the smart planner picks cue recall.
    assert [item["segment_id"] for item in body["items"]] == [first["segment_id"]]
    assert body["items"][0]["mode"] == "cue_recall"


def test_weak_links_report_mean_latency(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    for item, latency in zip(session["items"], (1200, 4800), strict=False):
        client.post(
            f"/api/v1/sessions/{session['id']}/attempts",
            json={"item_id": item["id"], "rating": "hesitant", "latency_ms": latency},
            headers=mutation(),
        )
    weak = client.get(f"/api/v1/analytics/weak-links?revision_id={revision['id']}").json()
    # Equal difficulty rates, so latency decides the order.
    assert [entry["mean_latency_ms"] for entry in weak] == [4800, 1200]


def test_undo_rewinds_review_state_and_reopens_item(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    first = session["items"][0]
    segment_id = first["segment_id"]

    graded = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "clean", "latency_ms": 900},
        headers=mutation(),
    ).json()
    assert graded["session"]["items"][0]["completed"] is True
    assert graded["session"]["current_index"] == 1
    # The clean grade created a review state for a previously-unseen segment.
    mastery_after = client.get("/api/v1/analytics/mastery").json()
    assert any(state["segment_id"] == segment_id for state in mastery_after["items"])

    undone = client.post(f"/api/v1/sessions/{session['id']}/undo", headers=mutation())
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert body["items"][0]["completed"] is False
    assert body["current_index"] == 0
    assert body["status"] == "active"
    # The snapshot said no state existed, so undo deleted the one it created.
    mastery = client.get("/api/v1/analytics/mastery").json()
    assert all(state["segment_id"] != segment_id for state in mastery["items"])

    empty = client.post(f"/api/v1/sessions/{session['id']}/undo", headers=mutation())
    assert empty.status_code == 409


def test_reveal_flag_is_independent_of_rating(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    first = session["items"][0]
    result = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "clean", "revealed": True, "latency_ms": 700},
        headers=mutation(),
    ).json()
    # Peeking is recorded but does not drag a clean grade down to "revealed".
    assert result["attempt"]["revealed"] is True
    assert result["attempt"]["rating"] == "clean"
    assert result["mastery_stage"] != "new"


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
    assert asset["cue_points"] == []

    listed = client.get(f"/api/v1/media?revision_id={revision['id']}&category=reference")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [asset["id"]]
    assert client.get("/api/v1/media?category=unsupported").status_code == 422

    cues = client.put(
        f"/api/v1/media/{asset['id']}/cues",
        json={
            "cue_points": [
                {"label": "second line", "time": 9.5},
                {"label": "opening", "time": 0},
            ]
        },
        headers=mutation(),
    )
    assert cues.status_code == 200, cues.text
    assert cues.json()["cue_points"] == [
        {"label": "opening", "time": 0.0, "segment_id": None, "end": None},
        {"label": "second line", "time": 9.5, "segment_id": None, "end": None},
    ]
    assert (
        client.get(f"/api/v1/media?revision_id={revision['id']}").json()[0]["cue_points"]
        == cues.json()["cue_points"]
    )

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


def test_cue_points_are_validated(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
) -> None:
    assert (
        client.put(
            "/api/v1/media/missing/cues",
            json={"cue_points": [{"label": "opening", "time": 0}]},
            headers=mutation(),
        ).status_code
        == 404
    )
    invalid = client.put(
        "/api/v1/media/missing/cues",
        json={"cue_points": [{"label": "", "time": -1}]},
        headers=mutation(),
    )
    assert invalid.status_code == 422


def test_prep_suggestions_fill_gaps_without_overwriting(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_generate(language_name: str, lines: list[str]) -> list[prep.LineSuggestion]:
        assert language_name == "Ancient Greek"
        return [
            prep.LineSuggestion(
                index=index,
                cue=f"cue {index}",
                glosses=[prep.WordGloss(word_index=0, gloss=f"gloss {index}")],
                translation=f"translation {index}",
            )
            for index in range(len(lines))
        ]

    monkeypatch.setattr(prep, "_generate", stub_generate)
    revision = passage["active_revision"]
    response = client.post(
        f"/api/v1/revisions/{revision['id']}/prep-suggestions",
        json={},
        headers=mutation(),
    )
    assert response.status_code == 200
    # Both lines already had authored cues; line 1 already had a translation.
    assert response.json()["written"] == {"cue": 0, "gloss": 2, "translation": 1}

    refreshed = client.get(f"/api/v1/revisions/{revision['id']}").json()
    lines = sorted(
        (segment for segment in refreshed["segments"] if segment["kind"] == "line"),
        key=lambda segment: segment["ordinal"],
    )
    # Authored content survives; drafts only fill the gaps.
    assert lines[0]["cue"] == "Sing, goddess"
    layers0 = {a["layer"]: a["value"] for a in lines[0]["annotations"]}
    assert layers0["translation"] == "Sing, goddess, the anger of Achilles"
    assert layers0["gloss"] == "gloss 0"
    layers1 = {a["layer"]: a["value"] for a in lines[1]["annotations"]}
    assert layers1["translation"] == "translation 1"

    unknown = client.post(
        f"/api/v1/revisions/{revision['id']}/prep-suggestions",
        json={"layers": ["meter"]},
        headers=mutation(),
    )
    assert unknown.status_code == 422


def test_prep_suggestions_unavailable_without_key(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raising(language_name: str, lines: list[str]) -> list[prep.LineSuggestion]:
        raise prep.PrepUnavailableError("GEMINI_API_KEY is not configured.")

    monkeypatch.setattr(prep, "_generate", raising)
    revision = passage["active_revision"]
    response = client.post(
        f"/api/v1/revisions/{revision['id']}/prep-suggestions",
        json={},
        headers=mutation(),
    )
    assert response.status_code == 503


def test_mastery_index_is_paginated(
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
    for item in session["items"]:
        response = client.post(
            f"/api/v1/sessions/{session['id']}/attempts",
            json={"item_id": item["id"], "rating": "clean"},
            headers=mutation(),
        )
        assert response.status_code == 201

    first_page = client.get("/api/v1/analytics/mastery?limit=1&offset=0")
    assert first_page.status_code == 200
    # Two lines plus the auto-generated juncture between them.
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["limit"] == 1
    assert first_page.json()["offset"] == 0

    second_page = client.get("/api/v1/analytics/mastery?limit=1&offset=1")
    assert len(second_page.json()["items"]) == 1
    assert (
        first_page.json()["items"][0]["segment_id"] != second_page.json()["items"][0]["segment_id"]
    )
    assert client.get("/api/v1/analytics/mastery?limit=0").status_code == 422
