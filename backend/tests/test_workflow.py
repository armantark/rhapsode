from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from rhapsode.app import create_app
from rhapsode.services import planning, prep


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
    # Never-acquired lines get the composite first lesson.
    assert {item["mode"] for item in session["items"]} == {"acquisition"}


def test_acquisition_failure_retries_once_at_session_tail(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    first, intervening = session["items"]

    failed = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "incorrect", "revealed": True},
        headers=mutation(),
    )
    assert failed.status_code == 201, failed.text
    after_failure = failed.json()["session"]
    assert after_failure["current_index"] == intervening["position"]
    assert len(after_failure["items"]) == 3
    retry = after_failure["items"][-1]
    assert retry["position"] > intervening["position"]
    assert retry["segment_id"] == first["segment_id"]
    assert retry["mode"] == "acquisition"
    assert "retry_source_item_id" not in retry
    assert failed.json()["mastery_stage"] == "new"

    # The intervening line is completed before the generated tail retry.
    advanced = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": intervening["id"], "rating": "hesitant", "revealed": True},
        headers=mutation(),
    ).json()["session"]
    assert advanced["current_index"] == retry["position"]

    # A retry is terminal even when it fails; it never recursively appends.
    retried = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": retry["id"], "rating": "revealed", "revealed": True},
        headers=mutation(),
    )
    assert retried.status_code == 201, retried.text
    assert len(retried.json()["session"]["items"]) == 3
    assert retried.json()["session"]["status"] == "completed"


def test_acquisition_retry_and_source_undo_restore_exact_state(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from sqlalchemy import select

    from rhapsode import models

    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    first, source = session["items"]

    # Good is a successful acquisition: it enters learning and adds no retry.
    first_result = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": first["id"], "rating": "hesitant", "revealed": True},
        headers=mutation(),
    ).json()
    assert first_result["mastery_stage"] == "learning"
    assert len(first_result["session"]["items"]) == 2

    source_result = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": source["id"], "rating": "incorrect", "revealed": True},
        headers=mutation(),
    ).json()
    retry = source_result["session"]["items"][-1]
    assert retry["segment_id"] == source["segment_id"]

    client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": retry["id"], "rating": "clean", "revealed": True},
        headers=mutation(),
    )

    # First undo reopens the retry and restores the source failure snapshot,
    # including acquisition_succeeded=False.
    retry_undone = client.post(
        f"/api/v1/sessions/{session['id']}/undo", headers=mutation()
    ).json()
    assert len(retry_undone["items"]) == 3
    assert retry_undone["items"][-1]["completed"] is False
    assert retry_undone["current_index"] == retry["position"]
    with session_factory() as db:  # type: ignore[operator]
        state = db.scalar(
            select(models.ReviewState).where(
                models.ReviewState.segment_id == source["segment_id"]
            )
        )
        assert state is not None
        assert state.acquisition_succeeded is False
        assert state.mastery_stage == "new"

    # The next undo targets the source failure. Its unattempted generated retry
    # disappears and the original two-item plan/state return exactly.
    source_undone = client.post(
        f"/api/v1/sessions/{session['id']}/undo", headers=mutation()
    ).json()
    assert len(source_undone["items"]) == 2
    assert source_undone["current_index"] == source["position"]
    assert source_undone["items"][0]["completed"] is True
    assert source_undone["items"][1]["completed"] is False
    with session_factory() as db:  # type: ignore[operator]
        state = db.scalar(
            select(models.ReviewState).where(
                models.ReviewState.segment_id == source["segment_id"]
            )
        )
        assert state is None


def test_manual_acquisition_is_rejected_as_coach_only(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    response = client.post(
        "/api/v1/sessions",
        json={
            "revision_id": revision["id"],
            "modes": ["acquisition"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    )
    assert response.status_code == 422
    assert "coach-only" in response.json()["detail"]


def test_smart_session_random_start_targets_are_shuffled(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from datetime import UTC, datetime

    from rhapsode import models

    def reverse(items: list[models.Segment]) -> None:
        items.reverse()

    monkeypatch.setattr(planning.random, "shuffle", reverse)
    revision = passage["active_revision"]
    lines = [segment for segment in revision["segments"] if segment["kind"] == "line"]
    with session_factory() as db:  # type: ignore[operator]
        for segment in lines:
            db.add(
                models.ReviewState(
                    segment_id=segment["id"],
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="review",
                    clean_count=2,
                    attempt_count=2,
                )
            )
        db.commit()

    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "segment_kinds": ["line"]},
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    random_items = [
        item for item in created.json()["items"] if item["mode"] == "random_start"
    ]
    assert [item["prompt"]["target_text"] for item in random_items] == [
        segment["text"] for segment in reversed(lines)
    ]


def test_chaining_attempt_reviews_every_line_in_the_chain(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    created = client.post(
        "/api/v1/sessions",
        json={
            "revision_id": revision["id"],
            "modes": ["forward_chaining"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    chained = next(item for item in session["items"] if len(item["prompt"]["chain"]) > 1)
    chain_segment_ids = set(chained["prompt"]["chain_segment_ids"])

    attempted = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": chained["id"], "rating": "clean"},
        headers=mutation(),
    )
    assert attempted.status_code == 201, attempted.text

    reviewed = {
        state["segment_id"]
        for state in client.get("/api/v1/analytics/mastery").json()["items"]
    }
    assert chain_segment_ids.issubset(reviewed)


def test_session_listing_expires_abandoned_sessions(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from datetime import UTC, datetime, timedelta

    from rhapsode import models

    revision = passage["active_revision"]
    stale = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    recent = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    with session_factory() as db:  # type: ignore[operator]
        row = db.get(models.PracticeSession, stale["id"])
        assert row is not None
        row.updated_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()

    default_listing = client.get("/api/v1/sessions").json()
    assert {session["id"] for session in default_listing} == {recent["id"]}
    expired_listing = client.get("/api/v1/sessions?status=expired").json()
    assert [session["id"] for session in expired_listing] == [stale["id"]]
    assert client.get(f"/api/v1/sessions/{stale['id']}").json()["status"] == "expired"

    rejected = client.post(
        f"/api/v1/sessions/{stale['id']}/attempts",
        json={"item_id": stale["items"][0]["id"], "rating": "clean"},
        headers=mutation(),
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Session is not active."


def test_append_lines_to_practiced_revision_preserves_progress(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    lines_before = [s for s in revision["segments"] if s["kind"] == "line"]
    first_line = lines_before[0]

    # Practice a line so it carries a review state, then confirm the revision
    # is now immutable to edits (replace 409s).
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    item = next(i for i in session["items"] if i["segment_id"] == first_line["id"])
    client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": item["id"], "rating": "clean"},
        headers=mutation(),
    )
    before = {s["segment_id"] for s in client.get("/api/v1/analytics/mastery").json()["items"]}
    assert first_line["id"] in before
    rejected = client.put(
        f"/api/v1/revisions/{revision['id']}/segments",
        json={"segments": [{"client_id": "x", "kind": "line", "ordinal": 0, "text": "νέος"}]},
        headers=mutation(),
    )
    assert rejected.status_code == 409

    # Appending new lines is allowed and leaves the practiced lines untouched.
    new_lines = [
        {"client_id": "new-1", "kind": "line", "ordinal": 0, "text": "πρῶτος στίχος"},
        {"client_id": "new-2", "kind": "line", "ordinal": 1, "text": "δεύτερος στίχος"},
    ]
    appended = client.post(
        f"/api/v1/revisions/{revision['id']}/segments",
        json={"segments": new_lines},
        headers=mutation(),
    )
    assert appended.status_code == 200, appended.text
    body = appended.json()
    lines_after = [s for s in body["segments"] if s["kind"] == "line"]
    # Every prior line survives with its exact id; the two new lines follow.
    assert {s["id"] for s in lines_before} <= {s["id"] for s in lines_after}
    assert len(lines_after) == len(lines_before) + 2
    assert body["source_text"].strip().endswith("δεύτερος στίχος")

    # The practiced line keeps its review state — no progress was orphaned.
    after = {s["segment_id"] for s in client.get("/api/v1/analytics/mastery").json()["items"]}
    assert first_line["id"] in after
    # A juncture now bridges the old last line into the first appended line.
    junctures = [s for s in body["segments"] if s["kind"] == "juncture"]
    assert len(junctures) >= len(lines_before)


def test_personal_note_overlay_updates_practiced_revision_hint(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    segment = revision["segments"][0]
    practiced = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    )
    assert practiced.status_code == 201, practiced.text
    assert client.get(f"/api/v1/segments/{segment['id']}/note").status_code == 404

    saved = client.put(
        f"/api/v1/segments/{segment['id']}/note",
        json={"text": "boulē → tabouleh"},
        headers=mutation(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["segment_id"] == segment["id"]
    assert saved.json()["text"] == "boulē → tabouleh"
    fetched = client.get(f"/api/v1/segments/{segment['id']}/note").json()
    assert fetched["segment_id"] == segment["id"]
    assert fetched["text"] == "boulē → tabouleh"
    assert fetched["updated_at"]

    updated = client.put(
        f"/api/v1/segments/{segment['id']}/note",
        json={"text": "mēnin → main in"},
        headers=mutation(),
    )
    assert updated.status_code == 200, updated.text
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    item = next(item for item in session["items"] if item["segment_id"] == segment["id"])
    assert item["prompt"]["hint"] == "mēnin → main in"

    refreshed = client.get(f"/api/v1/revisions/{revision['id']}").json()
    assert refreshed["practiced"] is True
    assert refreshed["segments"][0]["cue"] == segment["cue"]
    assert (
        client.put(
            "/api/v1/segments/missing/note",
            json={"text": "missing"},
            headers=mutation(),
        ).status_code
        == 404
    )


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

    full_passages = client.post(
        "/api/v1/sessions",
        json={
            "collection_id": collection["id"],
            "modes": ["full_passage"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    ).json()
    second_item = next(
        item for item in full_passages["items"] if item["revision_id"] == second_revision_id
    )
    graded = client.post(
        f"/api/v1/sessions/{full_passages['id']}/attempts",
        json={"item_id": second_item["id"], "rating": "clean"},
        headers=mutation(),
    )
    assert graded.status_code == 201, graded.text
    reviewed_ids = {
        state["segment_id"] for state in client.get("/api/v1/analytics/mastery").json()["items"]
    }
    assert reviewed_ids == {
        segment["id"] for segment in second["active_revision"]["segments"]
    }


def test_source_references_round_trip_into_chaining_prompts(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    greek_passage_payload: dict[str, object],
) -> None:
    source_segments = greek_passage_payload["segments"]
    assert isinstance(source_segments, list)
    referenced_segments: list[dict[str, object]] = []
    for index, segment in enumerate(source_segments):
        assert isinstance(segment, dict)
        referenced_segments.append(
            {**segment, "reference_label": f"Iliad 1.{index + 6}"}
        )
    payload = {
        **greek_passage_payload,
        "title": "Iliad reference contract",
        "reference_label": "Iliad 1.6–7",
        "segments": referenced_segments,
    }
    created = client.post("/api/v1/passages", json=payload, headers=mutation()).json()
    revision = created["active_revision"]

    assert revision["reference_label"] == "Iliad 1.6–7"
    assert [
        segment["reference_label"]
        for segment in revision["segments"]
        if segment["kind"] == "line"
    ] == ["Iliad 1.6", "Iliad 1.7"]

    session = client.post(
        "/api/v1/sessions",
        json={
            "revision_id": revision["id"],
            "modes": ["forward_chaining"],
            "segment_kinds": ["line"],
        },
        headers=mutation(),
    ).json()

    assert session["items"][0]["prompt"]["range_label"] == "Iliad 1.6"
    assert session["items"][1]["prompt"]["range_label"] == (
        "Iliad 1.6 through Iliad 1.7"
    )


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
    # Only the single graded-and-now-due segment is in the plan. It is still
    # learning, but cue recall was just used, so the rotation introduces the
    # least-used learning exercise (word bank) instead of repeating.
    assert [item["segment_id"] for item in body["items"]] == [first["segment_id"]]
    assert body["items"][0]["mode"] == "word_bank"


def _tokenized_passage(
    client: TestClient, mutation: Callable[..., dict[str, str]], greek_id: str
) -> dict[str, object]:
    """A passage segmented at both grains the whitespace default produces: one
    line plus its word tokens. Tokens carry glosses for reading but are never
    review units, which is exactly the mismatch the fixes below guard."""
    payload = {
        "title": "Iliad token regression",
        "language_profile_id": greek_id,
        "source_text": "μῆνιν ἄειδε θεά",
        "segments": [
            {"client_id": "line-1", "kind": "line", "ordinal": 0, "text": "μῆνιν ἄειδε θεά"},
            {"client_id": "t0", "parent_client_id": "line-1", "kind": "token", "ordinal": 0,
             "text": "μῆνιν"},
            {"client_id": "t1", "parent_client_id": "line-1", "kind": "token", "ordinal": 1,
             "text": "ἄειδε"},
            {"client_id": "t2", "parent_client_id": "line-1", "kind": "token", "ordinal": 2,
             "text": "θεά"},
        ],
    }
    response = client.post("/api/v1/passages", json=payload, headers=mutation())
    assert response.status_code == 201, response.text
    return response.json()


def test_full_passage_grade_skips_word_tokens(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    greek_id: str,
) -> None:
    """Root cause: a full-passage recitation must advance only review units.
    Fanning the grade onto word tokens minted states the planner could never
    schedule, surfacing them as permanently-due-yet-unpracticeable segments."""
    revision = _tokenized_passage(client, mutation, greek_id)["active_revision"]
    token_ids = {s["id"] for s in revision["segments"] if s["kind"] == "token"}
    assert token_ids

    full_passage = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["full_passage"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    graded = client.post(
        f"/api/v1/sessions/{full_passage['id']}/attempts",
        json={"item_id": full_passage["items"][0]["id"], "rating": "clean"},
        headers=mutation(),
    )
    assert graded.status_code == 201, graded.text

    reviewed = {s["segment_id"] for s in client.get("/api/v1/analytics/mastery").json()["items"]}
    assert reviewed, "the line should have gained a review state"
    assert not (reviewed & token_ids), "tokens must not receive review states"


def test_stale_token_states_do_not_strand_due_review(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    greek_id: str,
) -> None:
    """Regression for the 'Target has no practiceable segments' 422: even when
    a word token already holds a due review state (left by the pre-fix bug), it
    must neither appear in the due listing nor block the due-review session."""
    from datetime import UTC, datetime, timedelta

    from fsrs import Card
    from sqlalchemy import update

    from rhapsode import models

    revision = _tokenized_passage(client, mutation, greek_id)["active_revision"]
    line_id = next(s["id"] for s in revision["segments"] if s["kind"] == "line")
    token_ids = {s["id"] for s in revision["segments"] if s["kind"] == "token"}

    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": session["items"][0]["id"], "rating": "hesitant"},
        headers=mutation(),
    )

    with session_factory() as db:  # type: ignore[operator]
        db.add(
            models.ReviewState(
                segment_id=next(iter(token_ids)),
                fsrs_card_json=Card().to_json(),
                due_at=datetime.now(UTC) - timedelta(days=1),
                mastery_stage="learning",
                clean_count=0,
                attempt_count=1,
            )
        )
        # Backdate the legitimate line state too, so it is genuinely due now.
        db.execute(update(models.ReviewState).values(due_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()

    due_ids = {state["segment_id"] for state in client.get("/api/v1/analytics/due").json()}
    assert line_id in due_ids
    assert not (due_ids & token_ids), "tokens must be hidden from the due listing"

    due_session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "due_only": True},
        headers=mutation(),
    )
    assert due_session.status_code == 201, due_session.text
    planned = {item["segment_id"] for item in due_session.json()["items"]}
    assert line_id in planned
    assert not (planned & token_ids)


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


def test_review_logs_persist_per_grade_and_undo_retracts_them(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from sqlalchemy import func, select

    from rhapsode import models

    revision = passage["active_revision"]
    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    )
    session = created.json()
    attempted = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={"item_id": session["items"][0]["id"], "rating": "hesitant", "latency_ms": 2100},
        headers=mutation(),
    )
    assert attempted.status_code == 201, attempted.text

    def log_count() -> int:
        with session_factory() as db:  # type: ignore[operator]
            return db.scalar(select(func.count(models.FsrsReviewLog.id))) or 0

    assert log_count() == 1
    with session_factory() as db:  # type: ignore[operator]
        log = db.scalars(select(models.FsrsReviewLog)).one()
        assert log.rating == 3  # hesitant → FSRS Good
        assert log.review_duration_ms == 2100

    # Undo deletes the attempt; the log must cascade with it so the optimizer
    # never trains on retracted reviews.
    undone = client.post(f"/api/v1/sessions/{session['id']}/undo", headers=mutation())
    assert undone.status_code == 200, undone.text
    assert log_count() == 0


def test_delete_passage_removes_rows_and_media_files(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
    tmp_path: object,
) -> None:
    from pathlib import Path

    from sqlalchemy import func, select

    from rhapsode import models

    revision = passage["active_revision"]
    # Practice once so review states and a session exist, then attach media.
    seeded = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    client.post(
        f"/api/v1/sessions/{seeded['id']}/attempts",
        json={"item_id": seeded["items"][0]["id"], "rating": "hesitant"},
        headers=mutation(),
    )
    media_file = Path(str(tmp_path)) / "reference.mp3"
    media_file.write_bytes(b"fake-audio")
    with session_factory() as db:  # type: ignore[operator]
        db.add(
            models.MediaAsset(
                revision_id=revision["id"],
                category="reference",
                mime_type="audio/mpeg",
                original_name="reference.mp3",
                storage_path=str(media_file),
                size_bytes=10,
                cue_points=[],
            )
        )
        db.commit()

    deleted = client.delete(f"/api/v1/passages/{passage['id']}", headers=mutation())
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/v1/passages/{passage['id']}").status_code == 404
    # The media file left the disk with the rows.
    assert not media_file.exists()
    with session_factory() as db:  # type: ignore[operator]
        for model in (models.Segment, models.ReviewState, models.PracticeSession):
            assert (db.scalar(select(func.count()).select_from(model)) or 0) == 0


def test_library_stats_report_per_passage_progress(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    # Fresh passage: present but not started.
    stats = client.get("/api/v1/analytics/library").json()
    assert len(stats) == 1
    entry = stats[0]
    assert entry["passage_id"] == passage["id"]
    assert entry["started"] is False
    # 2 lines + 1 juncture are the practiceable units.
    assert entry["total_units"] == 3
    assert entry["due"] == 0

    revision = passage["active_revision"]
    seeded = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    client.post(
        f"/api/v1/sessions/{seeded['id']}/attempts",
        json={"item_id": seeded["items"][0]["id"], "rating": "hesitant"},
        headers=mutation(),
    )
    entry = client.get("/api/v1/analytics/library").json()[0]
    assert entry["started"] is True
    assert entry["learning"] == 1


def test_library_wide_today_queue(
    client: TestClient,
    session_factory: object,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from rhapsode import models

    # A targetless session is only valid as the due-only Today queue.
    rejected = client.post("/api/v1/sessions", json={}, headers=mutation())
    assert rejected.status_code == 422

    # Nothing due yet: the banner shows zero and a launch attempt 422s.
    empty = client.get("/api/v1/analytics/today").json()
    assert empty["due_count"] == 0
    assert empty["estimated_minutes"] == 0
    no_due = client.post("/api/v1/sessions", json={"due_only": True}, headers=mutation())
    assert no_due.status_code == 422

    # Grade one line, then force it due.
    revision = passage["active_revision"]
    seeded = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    ).json()
    for item in seeded["items"]:
        client.post(
            f"/api/v1/sessions/{seeded['id']}/attempts",
            json={"item_id": item["id"], "rating": "hesitant"},
            headers=mutation(),
        )
    with session_factory() as db:  # type: ignore[operator]
        db.execute(
            update(models.ReviewState).values(due_at=datetime.now(UTC) - timedelta(days=1))
        )
        db.commit()

    banner = client.get("/api/v1/analytics/today").json()
    assert banner["due_count"] == 2
    assert banner["estimated_minutes"] >= 1
    # The seeding session completed, so the streak is alive today.
    assert banner["streak_days"] == 1
    assert banner["forecast"][0]["due"] == 2

    launched = client.post("/api/v1/sessions", json={"due_only": True}, headers=mutation())
    assert launched.status_code == 201, launched.text
    body = launched.json()
    assert body["revision_id"] is None
    assert body["plan"]["due_only"] is True
    # Every due segment is dealt — the Today queue is uncapped.
    assert {item["segment_id"] for item in body["items"]} >= set(
        state["segment_id"] for state in client.get("/api/v1/analytics/due").json()
    )


def test_recital_stumble_map_grades_each_line(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    from datetime import datetime

    revision = passage["active_revision"]
    lines = [s for s in revision["segments"] if s["kind"] == "line"]
    junctures = [s for s in revision["segments"] if s["kind"] == "juncture"]
    assert junctures, "fixture passage should auto-generate a juncture"

    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["recital"]},
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    assert [item["mode"] for item in session["items"]] == ["recital"]
    item = session["items"][0]

    # The stumble map must reference lines, not junctures.
    rejected = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={
            "item_id": item["id"],
            "rating": "incorrect",
            "stumbled_segment_ids": [junctures[0]["id"]],
        },
        headers=mutation(),
    )
    assert rejected.status_code == 422

    # Stumbled on line 2 only: it lapses, line 1 passes, and the juncture
    # leading into line 2 lapses with its landing line.
    attempted = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={
            "item_id": item["id"],
            "rating": "incorrect",
            "stumbled_segment_ids": [lines[1]["id"]],
        },
        headers=mutation(),
    )
    assert attempted.status_code == 201, attempted.text
    assert attempted.json()["session"]["status"] == "completed"

    states = client.get("/api/v1/analytics/mastery").json()["items"]
    due_by_segment = {
        state["segment_id"]: datetime.fromisoformat(state["due_at"]) for state in states
    }
    assert due_by_segment[lines[1]["id"]] < due_by_segment[lines[0]["id"]]
    assert due_by_segment[junctures[0]["id"]] < due_by_segment[lines[0]["id"]]


def test_stumble_map_is_recital_only(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"], "segment_kinds": ["line"]},
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    session = created.json()
    rejected = client.post(
        f"/api/v1/sessions/{session['id']}/attempts",
        json={
            "item_id": session["items"][0]["id"],
            "rating": "hesitant",
            "stumbled_segment_ids": [],
        },
        headers=mutation(),
    )
    assert rejected.status_code == 422


def test_meaning_recall_targets_only_translated_lines(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    lines = [s for s in revision["segments"] if s["kind"] == "line"]
    created = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["meaning_recall"]},
        headers=mutation(),
    )
    assert created.status_code == 201, created.text
    items = created.json()["items"]
    # Only line-1 carries a translation annotation in the fixture.
    assert [item["segment_id"] for item in items] == [lines[0]["id"]]
    prompt = items[0]["prompt"]
    assert prompt["translation"] == "Sing, goddess, the anger of Achilles"
    assert prompt["target_text"] == lines[0]["text"]


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
    def stub_generate(
        language_name: str, lines: list[str], api_key: str | None = None
    ) -> list[prep.LineSuggestion]:
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
    assert response.json()["written"] == {"cue": 0, "gloss": 2, "translation": 1, "reading": 0}

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
    def raising(
        language_name: str, lines: list[str], api_key: str | None = None
    ) -> list[prep.LineSuggestion]:
        raise prep.PrepUnavailableError("No Gemini API key is configured.")

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
