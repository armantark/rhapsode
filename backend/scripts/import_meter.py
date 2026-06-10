"""Backfill hexameter scansion onto a passage's line segments.

Reads David Chamberlain's syllable-level Iliad scansion (vendor/hypotactic,
CC BY 4.0) and attaches one `meter` annotation per line segment via the API.
We go through the API rather than the database so normal idempotency and
validation rules apply, and because the server is already running whenever
this app is in use.

The annotation `value` is the human-readable foot scheme; the syllable-level
detail goes into `data` so a future aligned renderer or rhythm-only practice
cue can be built without re-importing.

Usage:
    uv run python scripts/import_meter.py --book 1 --passage "Iliad"
"""

from __future__ import annotations

import argparse
import csv
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import httpx

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "hypotactic" / "iliad"
SOURCE_CREDIT = "hypotactic.com (David Chamberlain), CC BY 4.0"
LONG_MARK = "—"
SHORT_MARK = "◡"


@dataclass(frozen=True)
class Syllable:
    text: str
    length: str  # "long" | "short"
    foot: int
    word: int
    half: str  # "hemi1" | "hemi2"


@dataclass(frozen=True)
class ScannedLine:
    number: int
    syllables: tuple[Syllable, ...]

    def scheme(self) -> str:
        feet: dict[int, list[str]] = {}
        for syllable in self.syllables:
            mark = LONG_MARK if syllable.length == "long" else SHORT_MARK
            feet.setdefault(syllable.foot, []).append(mark)
        return " | ".join("".join(feet[foot]) for foot in sorted(feet))

    def data(self, book: int) -> dict[str, Any]:
        return {
            "source": SOURCE_CREDIT,
            "book": book,
            "line": self.number,
            "syllables": [
                {
                    "text": syllable.text,
                    "length": syllable.length,
                    "foot": syllable.foot,
                    "word": syllable.word,
                    "half": syllable.half,
                }
                for syllable in self.syllables
            ],
        }


def normalize(text: str) -> str:
    """Editions disagree on macrons, accents, and punctuation; matching on
    bare lowercase letters survives all of that."""
    decomposed = unicodedata.normalize("NFD", text)
    letters = [
        char for char in decomposed if unicodedata.category(char).startswith("L")
    ]
    return "".join(letters).lower().replace("ς", "σ")


def load_book(book: int) -> dict[str, ScannedLine]:
    path = VENDOR_DIR / f"iliad{book}.csv"
    if not path.exists():
        raise SystemExit(f"No scansion data at {path}")
    lines: dict[int, list[Syllable]] = {}
    with path.open(encoding="utf-8") as handle:
        rows = csv.reader(handle)
        next(rows)  # header
        for row in rows:
            if len(row) < 6 or not row[0].strip().isdigit():
                continue
            lines.setdefault(int(row[0]), []).append(
                Syllable(
                    text=row[1].strip(),
                    length=row[2].strip(),
                    foot=int(row[4].strip()),
                    word=int(row[3].strip()),
                    half=row[5].strip(),
                )
            )
    indexed: dict[str, ScannedLine] = {}
    for number, syllables in lines.items():
        key = normalize("".join(syllable.text for syllable in syllables))
        indexed[key] = ScannedLine(number=number, syllables=tuple(syllables))
    return indexed


def resolve_revision(client: httpx.Client, passage_query: str) -> dict[str, Any]:
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
    revision_id = matches[0]["active_revision_id"]
    return client.get(f"/api/v1/revisions/{revision_id}").json()  # type: ignore[no-any-return]


def post_annotation(
    client: httpx.Client, segment_id: str, scanned: ScannedLine, book: int
) -> None:
    payload = {
        "segment_id": segment_id,
        "layer": "meter",
        "value": scanned.scheme(),
        "data": scanned.data(book),
    }
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = client.post(
                "/api/v1/annotations",
                json=payload,
                # Deterministic key: retries and re-runs replay, never duplicate.
                headers={"Idempotency-Key": f"meter-{segment_id}"},
            )
            response.raise_for_status()
            return
        except httpx.HTTPError as error:
            last_error = error
    raise SystemExit(f"Failed to annotate segment {segment_id}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=int, required=True, help="Iliad book number")
    parser.add_argument(
        "--passage", required=True, help="Passage id or unique title substring"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    scanned_by_text = load_book(args.book)
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        revision = resolve_revision(client, args.passage)
        line_segments = [
            segment for segment in revision["segments"] if segment["kind"] == "line"
        ]
        todo: list[tuple[str, ScannedLine]] = []
        for segment in line_segments:
            if any(
                annotation["layer"] == "meter"
                for annotation in segment.get("annotations", [])
            ):
                print(f"skip (already annotated): {segment['text']}")
                continue
            key = normalize(segment["text"])
            scanned = scanned_by_text.get(key)
            if scanned is None:
                close = get_close_matches(key, scanned_by_text, n=1, cutoff=0.9)
                scanned = scanned_by_text[close[0]] if close else None
            if scanned is None:
                print(f"NO MATCH in book {args.book}: {segment['text']}", file=sys.stderr)
                continue
            todo.append((segment["id"], scanned))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(
                pool.map(
                    lambda item: post_annotation(client, item[0], item[1], args.book),
                    todo,
                )
            )
        for _, scanned in todo:
            print(f"{args.book}.{scanned.number}: {scanned.scheme()}")
        print(f"annotated {len(todo)} of {len(line_segments)} line segments")


if __name__ == "__main__":
    main()
