from datetime import UTC, datetime
from pathlib import Path

from rhapsode import models
from rhapsode.services.media import snapshot_sqlite
from rhapsode.services.planning import (
    BUILT_IN_MODES,
    build_plan,
    progressive_masks,
    prompt_for,
    register_practice_mode,
)
from rhapsode.services.scheduling import mastery_stage


def test_progressive_masks_remove_support() -> None:
    masks = progressive_masks("arma virumque cano")
    assert masks[0] == "arma virumque cano"
    assert masks[-1] == "… … …"


def test_all_practice_modes_build_a_prompt(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-test", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="arma virumque cano"
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=0, text="arma virumque cano"),
            models.Segment(kind="line", ordinal=1, text="Troiae qui primus ab oris"),
        ]
        db.add(passage)
        db.commit()
        plan = build_plan(db, revision, BUILT_IN_MODES, ["line"])
        assert {item["mode"] for item in plan} == set(BUILT_IN_MODES)
        assert all(item["prompt"]["instruction"] for item in plan)


def test_mastery_stages() -> None:
    state = models.ReviewState(
        segment_id="segment",
        fsrs_card_json="{}",
        due_at=datetime.now(UTC),
        attempt_count=1,
        clean_count=0,
    )
    assert mastery_stage(state) == "learning"
    state.clean_count = 2
    assert mastery_stage(state) == "review"
    state.clean_count = 5
    assert mastery_stage(state) == "durable"


def test_plugin_practice_mode_can_extend_prompts() -> None:
    register_practice_mode(
        "echo",
        lambda target, _context: {"instruction": "Echo aloud.", "target_text": target.text},
    )
    target = models.Segment(kind="line", ordinal=0, text="Հայ եմ")
    assert prompt_for("echo", target, [target])["target_text"] == "Հայ եմ"


def test_snapshot_sqlite_copies_existing_database(tmp_path: Path) -> None:
    source = tmp_path / "rhapsode.db"
    source.write_bytes(b"sqlite")
    destination = snapshot_sqlite(source, tmp_path / "backups")
    assert destination is not None
    assert destination.read_bytes() == b"sqlite"


def test_sqlite_uses_wal_mode(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        assert db.connection().exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
