import json
from pathlib import Path

from rhapsode.app import create_app
from rhapsode.schemas import PassageInput

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_exposes_required_api_groups() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/api/v1/health",
        "/api/v1/languages",
        "/api/v1/plugins",
        "/api/v1/passages",
        "/api/v1/passages/{passage_id}/revisions",
        "/api/v1/revisions/{revision_id}/segments",
        "/api/v1/annotations",
        "/api/v1/media",
        "/api/v1/media/{media_id}/cues",
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}/attempts",
        "/api/v1/analytics/due",
        "/api/v1/analytics/mastery",
        "/api/v1/analytics/weak-links",
        "/api/v1/settings/{key}",
    }
    assert required <= set(paths)


def test_multilingual_passage_fixtures_match_contract() -> None:
    fixtures = sorted((ROOT / "contracts" / "fixtures").glob("*-passage.json"))
    assert len(fixtures) == 4
    for fixture in fixtures:
        PassageInput.model_validate(json.loads(fixture.read_text()))
