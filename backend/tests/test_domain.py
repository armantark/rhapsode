import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rhapsode import models, schemas
from rhapsode.services import prep
from rhapsode.services.backup import (
    SNAPSHOT_RETENTION,
    snapshot_sqlite,
    startup_snapshot,
)
from rhapsode.services.passages import create_revision
from rhapsode.services.planning import (
    BUILT_IN_MODES,
    _difficult_segment_ids,
    build_plan,
    build_smart_plan,
    progressive_masks,
    prompt_for,
    register_practice_mode,
    smart_mode_for,
)
from rhapsode.services.scheduling import _next_clean_streak, mastery_stage


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


def test_clean_streak_regresses_mastery() -> None:
    # Again wipes the streak; Hard demotes one threshold step (grill B2).
    assert _next_clean_streak(5, "clean") == 6
    assert _next_clean_streak(5, "hesitant") == 5
    assert _next_clean_streak(5, "incorrect") == 2  # durable → review
    assert _next_clean_streak(3, "incorrect") == 0  # review → learning
    assert _next_clean_streak(7, "revealed") == 0


def test_difficulty_decays_after_two_consecutive_cleans(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-decay", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(3)
        ]
        db.add(passage)
        db.commit()
        repaired, recovering, relapsed = revision.segments
        session = models.PracticeSession(revision_id=revision.id, plan={})
        db.add(session)
        db.flush()
        item = models.PracticeItem(
            session_id=session.id, position=0, mode="cue_recall", prompt={}
        )
        db.add(item)
        db.flush()

        def attempt(segment: models.Segment, rating: str) -> None:
            db.add(
                models.Attempt(
                    session_id=session.id,
                    item_id=item.id,
                    segment_id=segment.id,
                    mode="cue_recall",
                    rating=rating,
                )
            )
            db.flush()

        attempt(repaired, "incorrect")
        attempt(repaired, "clean")
        attempt(repaired, "clean")
        attempt(recovering, "revealed")
        attempt(recovering, "clean")
        attempt(relapsed, "incorrect")
        attempt(relapsed, "clean")
        attempt(relapsed, "clean")
        attempt(relapsed, "revealed")
        db.commit()

        difficult = _difficult_segment_ids(db)
        assert repaired.id not in difficult
        assert recovering.id in difficult
        assert relapsed.id in difficult


def test_junctures_generated_between_lines(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-junctures", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="...",
                segments=[
                    schemas.SegmentInput(
                        kind="line", ordinal=0, text="Μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος"
                    ),
                    schemas.SegmentInput(
                        kind="line", ordinal=1, text="οὐλομένην ἣ μυρί Ἀχαιοῖς ἄλγε ἔθηκε"
                    ),
                ],
            ),
        )
        junctures = [s for s in revision.segments if s.kind == "juncture"]
        assert len(junctures) == 1
        # Cue is the tail of line N, target the head of line N+1.
        assert junctures[0].cue == "… θεὰ Πηληϊάδεω Ἀχιλῆος"
        assert junctures[0].text == "οὐλομένην ἣ μυρί …"

        # Auto grain deals lines + junctures, transition before landing line.
        plan = build_smart_plan(db, revision, None)
        kinds = {s.id: s.kind for s in revision.segments}
        planned = [kinds[item["segment_id"]] for item in plan]
        assert planned == ["line", "juncture", "line"]


def test_new_segments_shadow_first_when_reference_audio_exists(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-shadow", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="...",
                segments=[
                    schemas.SegmentInput(kind="line", ordinal=0, text="line one words"),
                    schemas.SegmentInput(kind="line", ordinal=1, text="line two words"),
                ],
            ),
        )

        # Without audio, brand-new lines go straight to fading.
        plan = build_smart_plan(db, revision, None)
        assert [item["mode"] for item in plan] == [
            "progressive_fading",
            "progressive_fading",
            "progressive_fading",
        ]

        db.add(
            models.MediaAsset(
                revision_id=revision.id,
                category="reference",
                mime_type="audio/mpeg",
                original_name="teacher.mp3",
                storage_path="ref/teacher.mp3",
                size_bytes=1,
            )
        )
        db.flush()

        # With audio, each new LINE shadows first, then fades; the juncture
        # is a fragment and skips the shadowing pass.
        plan = build_smart_plan(db, revision, None)
        kinds = {s.id: s.kind for s in revision.segments}
        assert [(kinds[item["segment_id"]], item["mode"]) for item in plan] == [
            ("line", "shadowing"),
            ("line", "progressive_fading"),
            ("juncture", "progressive_fading"),
            ("line", "shadowing"),
            ("line", "progressive_fading"),
        ]


def test_prep_glosses_attach_to_tokens(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-token-gloss", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="Μῆνιν ἄειδε θεά",
                segments=[
                    schemas.SegmentInput(
                        kind="line", ordinal=0, text="Μῆνιν ἄειδε θεά", client_id="l0"
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=0,
                        text="Μῆνιν",
                        parent_client_id="l0",
                        client_id="t0",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=1,
                        text="ἄειδε",
                        parent_client_id="l0",
                        client_id="t1",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=2,
                        text="θεά",
                        parent_client_id="l0",
                        client_id="t2",
                    ),
                ],
            ),
        )

        def stub(language_name: str, lines: list[str]) -> list[prep.LineSuggestion]:
            return [
                prep.LineSuggestion(
                    index=0,
                    cue="wrath song",
                    glosses=[
                        prep.WordGloss(word_index=0, gloss="μῆνις, acc. sg., wrath"),
                        prep.WordGloss(word_index=2, gloss="θεά, voc. sg., goddess"),
                        prep.WordGloss(word_index=9, gloss="out of range, dropped"),
                    ],
                    translation="Sing, goddess, the wrath",
                )
            ]

        written = prep.suggest_prep(db, revision, ["gloss"], generate=stub)
        assert written == {"gloss": 2}
        # expire_on_commit=False keeps the pre-write relationship cache alive.
        db.expire_all()
        tokens = sorted(
            (s for s in revision.segments if s.kind == "token"),
            key=lambda s: s.ordinal,
        )
        by_token = {
            token.text: [a.value for a in token.annotations if a.layer == "gloss"]
            for token in tokens
        }
        assert by_token == {
            "Μῆνιν": ["μῆνις, acc. sg., wrath"],
            "ἄειδε": [],
            "θεά": ["θεά, voc. sg., goddess"],
        }

        # Re-running never duplicates: existing token glosses are skipped.
        assert prep.suggest_prep(db, revision, ["gloss"], generate=stub) == {"gloss": 0}


def test_minutes_budget_sizes_session_and_prioritizes_finisher(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-budget", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(20)
        ]
        db.add(passage)
        db.commit()

        # Fresh passage, 5-minute budget, no latency history: defaults say
        # progressive_fading ≈ 75s, so 300s buys 4 items.
        plan = build_smart_plan(db, revision, ["line"], minutes=5)
        assert len(plan) == 4

        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="durable",
                    clean_count=5,
                    attempt_count=6,
                )
            )
        db.commit()

        # Fully graduated: the finisher is budgeted first (120s default),
        # leaving 180s for random_start (30s) maintenance → 6 items + finisher.
        plan = build_smart_plan(db, revision, ["line"], minutes=5)
        assert plan[-1]["mode"] == "full_passage"
        assert len(plan) == 7


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
    destination = snapshot_sqlite(source, tmp_path / "backups", "pre-migration")
    assert destination is not None
    assert destination.read_bytes() == b"sqlite"


def test_startup_snapshot_gates_on_age_and_prunes(tmp_path: Path) -> None:
    source = tmp_path / "rhapsode.db"
    source.write_bytes(b"sqlite")
    backups = tmp_path / "backups"

    first = startup_snapshot(source, backups)
    assert first is not None
    # A fresh snapshot exists, so a second startup within 24h is a no-op.
    assert startup_snapshot(source, backups) is None

    # Age the existing snapshot past the gate; startup snapshots resume.
    stale_mtime = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(first, (stale_mtime, stale_mtime))
    assert startup_snapshot(source, backups) is not None

    # Retention keeps the newest N snapshots regardless of label.
    for index in range(SNAPSHOT_RETENTION + 3):
        extra = snapshot_sqlite(source, backups, f"label{index}")
        assert extra is not None
    assert len(list(backups.glob("rhapsode-*.db"))) == SNAPSHOT_RETENTION


def test_sqlite_uses_wal_mode(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        assert db.connection().exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
