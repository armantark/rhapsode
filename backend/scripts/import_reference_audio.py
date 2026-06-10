"""Import David Chamberlain's CC-BY Iliad recitations as shadowing reference audio.

Recording yourself is opt-in and rarely used (grill D2); the valuable
direction is shadowing a fluent reconstructed-pronunciation recitation, which
encodes meter and pronunciation. Chamberlain published the whole Iliad in
100-line MP3s on archive.org, so this script fetches the requested span and
attaches it to a passage's active revision as `reference` media via the API.

Idempotent: skips files already present (matched by original filename).

Usage:
    uv run python scripts/import_reference_audio.py --passage "Iliad" --book 1 --lines 1-100
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# The archive.org item ids follow no single pattern across books, but book 1
# is the documented stable URL from hypotactic.com's podcast feed.
AUDIO_URLS: dict[tuple[int, str], str] = {
    (1, "1-100"): "https://archive.org/download/Iliad1458611/Iliad1_1-100.mp3",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)
def download(url: str, destination: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def resolve_revision_id(client: httpx.Client, passage_query: str) -> str:
    passages: list[dict[str, Any]] = client.get("/api/v1/passages").json()
    matches = [
        passage
        for passage in passages
        if passage_query == passage["id"]
        or passage_query.lower() in str(passage["title"]).lower()
    ]
    if len(matches) != 1:
        titles = ", ".join(str(passage["title"]) for passage in passages)
        raise SystemExit(
            f"Passage query {passage_query!r} matched {len(matches)} of: {titles}"
        )
    return str(matches[0]["active_revision_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passage", required=True, help="Passage id or title substring")
    parser.add_argument("--book", type=int, default=1)
    parser.add_argument("--lines", default="1-100", help="Line span, e.g. 1-100")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    url = AUDIO_URLS.get((args.book, args.lines))
    if url is None:
        known = ", ".join(f"book {book} lines {span}" for book, span in AUDIO_URLS)
        raise SystemExit(
            f"No known audio URL for book {args.book} lines {args.lines}. Known: {known}"
        )
    filename = f"chamberlain-iliad{args.book}-{args.lines}.mp3"

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        revision_id = resolve_revision_id(client, args.passage)
        existing = client.get(
            "/api/v1/media", params={"revision_id": revision_id, "category": "reference"}
        ).json()
        if any(item["original_name"] == filename for item in existing):
            print(f"skip: {filename} already attached to revision {revision_id}")
            return
        with tempfile.TemporaryDirectory() as scratch:
            audio_path = Path(scratch) / filename
            print(f"downloading {url} …")
            download(url, audio_path)
            with audio_path.open("rb") as handle:
                response = client.post(
                    "/api/v1/media",
                    data={"category": "reference", "revision_id": revision_id},
                    files={"upload": (filename, handle, "audio/mpeg")},
                    headers={"Idempotency-Key": f"reference-{revision_id}-{filename}"},
                )
            response.raise_for_status()
        print(f"attached {filename} ({response.json()['size_bytes']} bytes) as reference audio")


if __name__ == "__main__":
    main()
