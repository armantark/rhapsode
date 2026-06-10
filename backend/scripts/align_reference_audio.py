"""Align a reference recitation to passage lines by its pauses.

Forced alignment is unreliable for reconstructed-pronunciation Ancient Greek
(off-the-shelf acoustic models have never heard it), so instead of guessing
phonemes we lean on something the reader gives us for free: the silence between
lines. A deliberate recitation pauses at line ends, so the speech spans between
silences map onto lines in order. We write each line's span back as a
segment-linked cue point, and the practice loop uses those to jump the player
to the right line and loop just its span for shadowing.

This is a heuristic: a reader who pauses mid-line (caesura, breath) produces
extra spans. Tune --noise / --min-silence / --min-line until the printed span
count matches the line count, then the cues are written.

Usage:
    uv run python scripts/align_reference_audio.py --passage "Iliad" \
        --media "Iliad 1.1-22" --noise -30 --min-silence 0.28
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")


@dataclass(frozen=True)
class Span:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def detect_silences(path: Path, noise_db: float, min_silence: float) -> list[Span]:
    """Return silence intervals via ffmpeg's silencedetect filter."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    starts: list[float] = [float(m) for m in _SILENCE_START.findall(result.stderr)]
    ends: list[float] = [float(m) for m in _SILENCE_END.findall(result.stderr)]
    # silencedetect prints a start for every end, but a trailing silence at EOF
    # may lack its end; pair greedily and drop a dangling start.
    return [Span(start, end) for start, end in zip(starts, ends, strict=False)]


def speech_spans(silences: list[Span], duration: float, min_line: float) -> list[Span]:
    """Complement of the silence intervals over [0, duration], keeping only
    spans long enough to plausibly be a spoken line."""
    cursor = 0.0
    spans: list[Span] = []
    for silence in silences:
        if silence.start > cursor:
            spans.append(Span(cursor, silence.start))
        cursor = max(cursor, silence.end)
    if duration > cursor:
        spans.append(Span(cursor, duration))
    return [span for span in spans if span.duration >= min_line]


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
        raise SystemExit(f"Passage query {passage_query!r} matched {len(matches)} of: {titles}")
    return str(matches[0]["active_revision_id"])


def resolve_media(client: httpx.Client, revision_id: str, media_query: str) -> dict[str, Any]:
    media: list[dict[str, Any]] = client.get(
        "/api/v1/media", params={"revision_id": revision_id, "category": "reference"}
    ).json()
    matches = [m for m in media if media_query.lower() in str(m["original_name"]).lower()]
    if len(matches) != 1:
        names = ", ".join(str(m["original_name"]) for m in media) or "(none)"
        raise SystemExit(f"Media query {media_query!r} matched {len(matches)} of: {names}")
    return matches[0]


def line_segments(client: httpx.Client, revision_id: str) -> list[dict[str, Any]]:
    revision = client.get(f"/api/v1/revisions/{revision_id}").json()
    segments = [s for s in revision["segments"] if s["kind"] == "line"]
    return sorted(segments, key=lambda s: s["ordinal"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passage", required=True, help="Passage id or title substring")
    parser.add_argument("--media", required=True, help="Reference filename substring")
    parser.add_argument("--noise", type=float, default=-30.0, help="Silence threshold in dBFS")
    parser.add_argument("--min-silence", type=float, default=0.3, help="Min silence seconds")
    parser.add_argument("--min-line", type=float, default=0.4, help="Min line seconds")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--write", action="store_true", help="Persist cues (otherwise dry-run preview)"
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        revision_id = resolve_revision_id(client, args.passage)
        asset = resolve_media(client, revision_id, args.media)
        lines = line_segments(client, revision_id)
        if not lines:
            raise SystemExit("Revision has no line segments to align.")

        with tempfile.TemporaryDirectory() as scratch:
            audio_path = Path(scratch) / str(asset["original_name"])
            content = client.get(f"/api/v1/media/{asset['id']}/content")
            content.raise_for_status()
            audio_path.write_bytes(content.content)
            duration = probe_duration(audio_path)
            silences = detect_silences(audio_path, args.noise, args.min_silence)
            spans = speech_spans(silences, duration, args.min_line)

        print(f"duration {duration:.2f}s · {len(spans)} speech spans · {len(lines)} lines")
        if len(spans) < len(lines):
            raise SystemExit(
                "Fewer spans than lines — lower --min-silence or --noise so line "
                "breaks register, then rerun."
            )
        if len(spans) > len(lines):
            print(
                f"warning: {len(spans) - len(lines)} extra spans (mid-line pauses?). "
                "Aligning the first runs to lines in order; raise --min-silence to merge."
            )

        cues: list[dict[str, Any]] = []
        for index, segment in enumerate(lines):
            span = spans[index]
            preview = str(segment["text"])[:32]
            print(f"  line {segment['ordinal'] + 1}: {span.start:6.2f}–{span.end:6.2f}s  {preview}")
            cues.append(
                {
                    "label": f"line {segment['ordinal'] + 1}",
                    "time": round(span.start, 3),
                    "end": round(span.end, 3),
                    "segment_id": segment["id"],
                }
            )

        if not args.write:
            print("dry run — rerun with --write to persist these cues")
            return
        response = client.put(f"/api/v1/media/{asset['id']}/cues", json={"cue_points": cues})
        response.raise_for_status()
        print(f"wrote {len(cues)} segment-linked cues to {asset['original_name']}")


if __name__ == "__main__":
    main()
