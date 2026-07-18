"""Provision Iliad 1.11–20 and add it to the existing Iliad collection.

The Greek follows the Perseus edition already used by the live 1.8–10
passage. The line-by-line translations are authored for Rhapsode. Re-running
this command validates and reuses an exact existing passage instead of
creating duplicates.

Usage:
    uv run python scripts/provision_iliad_11_20.py
"""

from __future__ import annotations

import argparse
import json
from time import sleep
from typing import Any, Protocol

import httpx

from rhapsode.corpora.iliad import (
    BOOK_ONE_11_20,
    COLLECTION_NAME,
    PASSAGE_REFERENCE,
    PASSAGE_TITLE,
    passage_payload,
)


class Client(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


def request(client: Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code < 500:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"{response.status_code} from {url}",
                request=response.request,
                response=response,
            )
        except httpx.TransportError as error:
            last_error = error
        if attempt < 2:
            sleep(2**attempt)
    raise RuntimeError(f"Request failed after three attempts: {method} {url}") from last_error


def _validate_existing(passage: dict[str, Any]) -> None:
    revision = passage.get("active_revision")
    if not isinstance(revision, dict):
        raise RuntimeError(f"{PASSAGE_TITLE} has no active revision.")
    lines = sorted(
        (segment for segment in revision["segments"] if segment["kind"] == "line"),
        key=lambda segment: segment["ordinal"],
    )
    actual = [
        (
            line["text"],
            line["reference_label"],
            next(
                (
                    annotation["value"]
                    for annotation in line["annotations"]
                    if annotation["layer"] == "translation"
                ),
                None,
            ),
        )
        for line in lines
    ]
    expected = [
        (verse.text, f"Iliad 1.{verse.number}", verse.translation) for verse in BOOK_ONE_11_20
    ]
    if revision["reference_label"] != PASSAGE_REFERENCE or actual != expected:
        raise RuntimeError(
            f'Existing passage "{PASSAGE_TITLE}" does not match the curated excerpt.'
        )


def provision(client: Client, collection_name: str = COLLECTION_NAME) -> dict[str, Any]:
    languages = request(client, "GET", "/api/v1/languages").json()
    greek = next(
        (profile for profile in languages if profile["slug"] == "ancient-greek"),
        None,
    )
    if greek is None:
        raise RuntimeError("The Ancient Greek language profile is missing.")

    passages = request(client, "GET", "/api/v1/passages").json()
    matches = [passage for passage in passages if passage["title"] == PASSAGE_TITLE]
    if len(matches) > 1:
        raise RuntimeError(f'Multiple passages are titled "{PASSAGE_TITLE}".')
    if matches:
        passage = request(client, "GET", f"/api/v1/passages/{matches[0]['id']}").json()
        _validate_existing(passage)
        passage_action = "reused"
    else:
        passage = request(
            client,
            "POST",
            "/api/v1/passages",
            json=passage_payload(greek["id"]),
            headers={"Idempotency-Key": "provision-iliad-1-11-20"},
        ).json()
        passage_action = "created"

    collections = request(client, "GET", "/api/v1/collections").json()
    collection_matches = [
        collection for collection in collections if collection["name"] == collection_name
    ]
    if len(collection_matches) != 1:
        raise RuntimeError(
            f'Expected one collection titled "{collection_name}", found {len(collection_matches)}.'
        )
    collection = collection_matches[0]
    if any(member["passage_id"] == passage["id"] for member in collection["members"]):
        collection_action = "already linked"
    else:
        collection = request(
            client,
            "POST",
            f"/api/v1/collections/{collection['id']}/members",
            json={"passage_id": passage["id"]},
            headers={"Idempotency-Key": "link-iliad-1-11-20"},
        ).json()
        collection_action = "linked"

    return {
        "passage_action": passage_action,
        "collection_action": collection_action,
        "passage": passage,
        "collection": collection,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--collection", default=COLLECTION_NAME)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        result = provision(client, args.collection)
    print(
        json.dumps(
            {
                "passage": f"{result['passage_action']}: {PASSAGE_REFERENCE}",
                "collection": f"{result['collection_action']}: {args.collection}",
                "lines": len(BOOK_ONE_11_20),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
