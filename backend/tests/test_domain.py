from datetime import UTC, datetime
from pathlib import Path

from rhapsode import models
from rhapsode.services.media import snapshot_sqlite
from rhapsode.services.planning import (
    BUILT_IN_MODES,
    build_plan,
    build_smart_plan,
    progressive_masks,
    prompt_for,
    register_practice_mode,
    smart_mode_for,
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


def test_smart_mode_ladder_fades_support_with_mastery() -> None:
    assert smart_mode_for(None, difficult=False) == "progressive_fading"
    assert smart_mode_for("new", difficult=False) == "progressive_fading"
    assert smart_mode_for("learning", difficult=False) == "cue_recall"
    assert smart_mode_for("review", difficult=False) == "random_start"
    assert smart_mode_for("durable", difficult=False) == "random_start"
    # Difficulty pulls a segment into weak-link drilling, but a brand-new
    # segment still needs scaffolding before being drilled cold.
    assert smart_mode_for("review", difficult=True) == "weak_link"
    assert smart_mode_for(None, difficult=True) == "progressive_fading"


def test_smart_plan_appends_full_passage_once_all_segments_graduate(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-smart", name="Latin")
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

        # Fresh segments: every item scaffolds, no holistic finisher yet.
        plan = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in plan] == ["progressive_fading", "progressive_fading"]

        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="review",
                    clean_count=2,
                    attempt_count=2,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in plan] == [
            "random_start",
            "random_start",
            "full_passage",
        ]


def test_smart_plan_caps_session_size_and_triages(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-epic", name="Ancient Greek")
        passage = models.Passage(title="Iliad 1", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        # 20 lines: 0-14 brand new, 15-19 already in "learning".
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(20)
        ]
        db.add(passage)
        db.commit()
        for segment in revision.segments[15:]:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        assert len(plan) == 12
        ordinals = {
            segment.id: segment.ordinal for segment in revision.segments
        }
        planned_ordinals = [ordinals[item["segment_id"]] for item in plan]
        # All five learning lines made the cut ahead of new material...
        assert set(planned_ordinals) >= {15, 16, 17, 18, 19}
        # ...and the session still flows in passage order.
        assert planned_ordinals == sorted(planned_ordinals)


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
