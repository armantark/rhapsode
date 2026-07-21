from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from rhapsode.corpora.iliad import (
    BOOK_ONE_11_20,
    COLLECTION_NAME,
    PASSAGE_REFERENCE,
    PASSAGE_TITLE,
    passage_payload,
)


def _provision_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts" / "provision_iliad_11_20.py"
    spec = spec_from_file_location("provision_iliad_11_20", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_iliad_11_20_payload_matches_the_existing_segment_shape() -> None:
    payload = passage_payload("greek")
    lines = [segment for segment in payload["segments"] if segment["kind"] == "line"]
    tokens = [segment for segment in payload["segments"] if segment["kind"] == "token"]

    assert payload["title"] == PASSAGE_TITLE
    assert payload["reference_label"] == PASSAGE_REFERENCE
    assert payload["source_text"].splitlines() == [verse.text for verse in BOOK_ONE_11_20]
    assert [line["reference_label"] for line in lines] == [
        f"Iliad 1.{number}" for number in range(11, 21)
    ]
    assert all(line["annotations"][0]["layer"] == "translation" for line in lines)
    for line in lines:
        line_tokens = [
            token["text"] for token in tokens if token["parent_client_id"] == line["client_id"]
        ]
        assert " ".join(line_tokens) == line["text"]


def test_iliad_11_20_provisioning_is_idempotent_and_collection_linked(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
) -> None:
    created_collection = client.post(
        "/api/v1/collections",
        json={"name": COLLECTION_NAME},
        headers=mutation("create-iliad-collection"),
    )
    assert created_collection.status_code == 201, created_collection.text
    provision = _provision_module().provision

    first = provision(client)
    second = provision(client)

    assert first["passage_action"] == "created"
    assert first["collection_action"] == "linked"
    assert second["passage_action"] == "reused"
    assert second["collection_action"] == "already linked"
    assert first["passage"]["id"] == second["passage"]["id"]
    passages = client.get("/api/v1/passages").json()
    assert len([passage for passage in passages if passage["title"] == PASSAGE_TITLE]) == 1
    revision = first["passage"]["active_revision"]
    assert len([segment for segment in revision["segments"] if segment["kind"] == "line"]) == 10
    assert len([segment for segment in revision["segments"] if segment["kind"] == "juncture"]) == 9
    assert second["collection"]["members"][-1]["passage_id"] == first["passage"]["id"]


def test_iliad_11_20_enters_the_settled_acquisition_learning_sequence(
    client: TestClient,
    mutation: Callable[..., dict[str, str]],
) -> None:
    collection = client.post(
        "/api/v1/collections",
        json={"name": COLLECTION_NAME},
        headers=mutation("create-staged-iliad-collection"),
    ).json()
    provisioned = _provision_module().provision(client)
    revision = provisioned["passage"]["active_revision"]

    line_session_response = client.post(
        "/api/v1/sessions",
        json={"collection_id": collection["id"], "segment_kinds": ["line"]},
        headers=mutation("start-iliad-line-acquisition"),
    )
    assert line_session_response.status_code == 201, line_session_response.text
    line_session = line_session_response.json()
    kinds = {segment["id"]: segment["kind"] for segment in revision["segments"]}
    # Ten provisioned lines must NOT arrive as a wall of first lessons: the
    # intro cap trickles them in two per session while the rest wait.
    assert [item["mode"] for item in line_session["items"]] == ["acquisition"] * 2

    auto_session = client.post(
        "/api/v1/sessions",
        json={"collection_id": collection["id"]},
        headers=mutation("start-iliad-auto-acquisition"),
    ).json()
    auto_plan = [(kinds[item["segment_id"]], item["mode"]) for item in auto_session["items"]]
    assert auto_plan
    # With no line yet started, junctures are gated entirely — a transition
    # between two unknown lines teaches nothing.
    assert all(kind == "line" and mode == "acquisition" for kind, mode in auto_plan)
    assert len(auto_plan) == 2

    first_line = line_session["items"][0]
    learned = client.post(
        f"/api/v1/sessions/{line_session['id']}/attempts",
        json={"item_id": first_line["id"], "rating": "hesitant", "revealed": True},
        headers=mutation("complete-first-iliad-acquisition"),
    )
    assert learned.status_code == 201, learned.text
    assert learned.json()["mastery_stage"] == "learning"
