from collections.abc import Callable

from fastapi.testclient import TestClient


def test_health_and_seeded_extensions(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert {item["slug"] for item in client.get("/api/v1/languages").json()} == {
        "ancient-greek",
        "classical-armenian",
        "japanese",
        "latin",
    }
    plugins = client.get("/api/v1/plugins").json()
    assert any(plugin["kind"] == "speech_scoring" and not plugin["enabled"] for plugin in plugins)


def test_mutations_require_and_replay_idempotency(
    client: TestClient, greek_passage_payload: dict[str, object]
) -> None:
    missing = client.post("/api/v1/passages", json=greek_passage_payload)
    assert missing.status_code == 400
    headers = {"Idempotency-Key": "same-create"}
    first = client.post("/api/v1/passages", json=greek_passage_payload, headers=headers)
    second = client.post("/api/v1/passages", json=greek_passage_payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotency-Replayed"] == "true"


def test_practiced_revision_is_immutable(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
    passage: dict[str, object],
) -> None:
    revision = passage["active_revision"]
    session = client.post(
        "/api/v1/sessions",
        json={"revision_id": revision["id"], "modes": ["cue_recall"]},
        headers=mutation(),
    )
    assert session.status_code == 201
    replaced = client.put(
        f"/api/v1/revisions/{revision['id']}/segments",
        json={"segments": []},
        headers=mutation(),
    )
    assert replaced.status_code == 409
    # Immutability protects the recall target, not the support layers:
    # annotations (meter, glosses) stay editable after practice begins.
    segment_id = revision["segments"][0]["id"]
    annotated = client.post(
        "/api/v1/annotations",
        json={"segment_id": segment_id, "layer": "meter", "value": "—◡◡"},
        headers=mutation(),
    )
    assert annotated.status_code == 201


def test_plugin_validation_and_settings(
    client: TestClient, mutation: Callable[..., dict[str, str]]
) -> None:
    invalid = client.post(
        "/api/v1/plugins",
        json={"plugin_id": "bad", "kind": "other", "name": "Bad", "version": "1"},
        headers=mutation(),
    )
    assert invalid.status_code == 422
    saved = client.put(
        "/api/v1/settings/theme",
        json={"value": "scholarly-arcade"},
        headers=mutation(),
    )
    assert saved.json() == {"key": "theme", "value": "scholarly-arcade"}
    assert client.get("/api/v1/settings").json() == [saved.json()]


def test_collection_crud_and_ordered_membership(
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
    created = client.post(
        "/api/v1/collections", json={"name": "Iliad Book 1"}, headers=mutation()
    )
    assert created.status_code == 201
    collection_id = created.json()["id"]

    first_added = client.post(
        f"/api/v1/collections/{collection_id}/members",
        json={"passage_id": passage["id"]},
        headers=mutation(),
    )
    assert first_added.status_code == 200
    assert first_added.json()["rollup"] == {"due": 0, "learning": 0, "new": 3}
    client.post(
        f"/api/v1/collections/{collection_id}/members",
        json={"passage_id": second["id"]},
        headers=mutation(),
    )
    duplicate = client.post(
        f"/api/v1/collections/{collection_id}/members",
        json={"passage_id": second["id"]},
        headers=mutation(),
    )
    assert duplicate.status_code == 409

    reordered = client.put(
        f"/api/v1/collections/{collection_id}/members",
        json={"passage_ids": [second["id"], passage["id"]]},
        headers=mutation(),
    )
    assert [member["passage_id"] for member in reordered.json()["members"]] == [
        second["id"],
        passage["id"],
    ]
    renamed = client.put(
        f"/api/v1/collections/{collection_id}",
        json={"name": "Iliad Opening"},
        headers=mutation(),
    )
    assert renamed.json()["name"] == "Iliad Opening"
    removed = client.delete(
        f"/api/v1/collections/{collection_id}/members/{second['id']}",
        headers=mutation(),
    )
    assert [member["position"] for member in removed.json()["members"]] == [0]
    assert len(client.get("/api/v1/collections").json()) == 1
    assert client.delete(f"/api/v1/collections/{collection_id}", headers=mutation()).json() == {
        "deleted": True
    }


def test_common_not_found_errors(
    client: TestClient, mutation: Callable[..., dict[str, str]]
) -> None:
    assert client.get("/api/v1/passages/missing").status_code == 404
    assert client.get("/api/v1/collections/missing").status_code == 404
    assert client.get("/api/v1/revisions/missing").status_code == 404
    assert client.get("/api/v1/sessions/missing").status_code == 404
    assert client.delete("/api/v1/media/missing", headers=mutation()).status_code == 404
