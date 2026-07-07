import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fsrs import Rating
from pydantic import ValidationError

from rhapsode import models, schemas
from rhapsode.services import furigana, planning, prep
from rhapsode.services import sessions as session_service
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
    build_smart_plan_for_revisions,
    progressive_masks,
    prompt_for,
    register_practice_mode,
    smart_mode_for,
)
from rhapsode.services.scheduling import RATING_MAP, _next_clean_streak, mastery_stage


def test_progressive_masks_fade_toward_the_opening_cue() -> None:
    # The opening is the retrieval cue (_lead_in doctrine), so support must
    # fade from the end: each stage demands a longer recalled tail, and the
    # last supported stage is the cue_recall shape.
    masks = progressive_masks("arma virumque cano")
    assert masks == [
        "arma virumque cano",
        "arma virumque ••••",
        "arma •••••••• ••••",
        "•••• •••••••• ••••",
    ]


def test_progressive_masks_handle_no_space_scripts_gradually() -> None:
    masks = progressive_masks("空こぼれ落ちた")

    assert masks == [
        "空こぼれ落ちた",
        "空こぼれ落••",
        "空こぼ••••",
        "空こ•••••",
        "•••••••",
    ]


def test_progressive_masks_never_hide_juncture_ellipsis() -> None:
    # A juncture head ends in "…" — a continuation marker, not recallable
    # content. It stays visible at every stage.
    masks = progressive_masks("Μοῦσα θεά ἄειδε …")
    assert masks == [
        "Μοῦσα θεά ἄειδε …",
        "Μοῦσα θεά ••••• …",
        "Μοῦσα ••• ••••• …",
        "••••• ••• ••••• …",
    ]


def test_all_practice_modes_build_a_prompt(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-test", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="arma virumque cano"
        )
        first = models.Segment(kind="line", ordinal=0, text="arma virumque cano")
        revision.segments = [
            first,
            models.Segment(kind="line", ordinal=1, text="Troiae qui primus ab oris"),
        ]
        db.add(passage)
        db.commit()
        # meaning_recall only targets translated lines, so one line carries one.
        annotation = models.Annotation(
            segment_id=first.id, layer="translation", value="I sing of arms and the man"
        )
        db.add(annotation)
        first.annotations.append(annotation)
        db.commit()
        plan = build_plan(db, revision, BUILT_IN_MODES, ["line"])
        assert {item["mode"] for item in plan} == set(BUILT_IN_MODES)
        assert all(item["prompt"]["instruction"] for item in plan)


def test_manual_random_start_uses_shuffled_target_order(
    monkeypatch: pytest.MonkeyPatch, session_factory: object
) -> None:
    def reverse(items: list[models.Segment]) -> None:
        items.reverse()

    monkeypatch.setattr(planning.random, "shuffle", reverse)
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-manual-random", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(4)
        ]
        db.add(passage)
        db.commit()

        plan = build_plan(db, revision, ["random_start"], ["line"])
        assert [item["prompt"]["target_text"] for item in plan] == [
            "line 3",
            "line 2",
            "line 1",
            "line 0",
        ]


def test_smart_mode_ladder_fades_support_with_mastery() -> None:
    assert smart_mode_for(None, difficult=False) == "progressive_fading"
    assert smart_mode_for("new", difficult=False) == "progressive_fading"
    # Learning lines rebuild order first (word bank), then produce (cue recall).
    assert smart_mode_for("learning", difficult=False) == "word_bank"
    assert smart_mode_for("review", difficult=False) == "random_start"
    assert smart_mode_for("durable", difficult=False) == "random_start"
    # Graduated lines earn the typed check right after cold starts.
    assert (
        smart_mode_for("review", difficult=False, mode_counts={"random_start": 1})
        == "typed_recall"
    )
    # Difficulty pulls a segment into weak-link drilling, but a brand-new
    # segment still needs scaffolding before being drilled cold.
    assert smart_mode_for("review", difficult=True) == "weak_link"
    assert smart_mode_for(None, difficult=True) == "progressive_fading"
    # Once a technique has been used, the coach deliberately introduces the
    # least-practiced useful exercise instead of repeating the same label.
    assert (
        smart_mode_for(
            "learning", difficult=False, mode_counts={"word_bank": 1, "cue_recall": 1}
        )
        == "forward_chaining"
    )
    assert (
        smart_mode_for(
            "review",
            difficult=True,
            mode_counts={"weak_link": 5, "random_start": 1, "typed_recall": 1},
        )
        == "forward_chaining"
    )
    # Transition fragments stay on transition-appropriate drills.
    assert (
        smart_mode_for(
            "learning",
            difficult=False,
            kind="juncture",
            mode_counts={"cue_recall": 1},
        )
        == "progressive_fading"
    )
    assert (
        smart_mode_for(
            "learning",
            difficult=False,
            mode_counts={
                "word_bank": 1,
                "cue_recall": 1,
                "forward_chaining": 1,
                "backward_chaining": 1,
                "progressive_fading": 1,
            },
            has_reference_audio=True,
        )
        == "shadowing"
    )


def test_smart_plan_rotates_line_exercises_and_builds_forward_context(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-rotation", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(3)
        ]
        db.add(passage)
        db.flush()
        history = models.PracticeSession(revision_id=revision.id, plan={})
        db.add(history)
        db.flush()
        for index, segment in enumerate(revision.segments):
            item = models.PracticeItem(
                session_id=history.id,
                revision_id=revision.id,
                segment_id=segment.id,
                position=index,
                mode="cue_recall",
                prompt={},
            )
            db.add(item)
            db.flush()
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=2,
                )
            )
            for mode in ("cue_recall", "progressive_fading", "word_bank"):
                db.add(
                    models.Attempt(
                        session_id=history.id,
                        item_id=item.id,
                        segment_id=segment.id,
                        mode=mode,
                        rating="hesitant",
                        review_snapshot=[],
                    )
                )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in plan] == ["forward_chaining"] * 3
        assert [item["prompt"]["chain"] for item in plan] == [
            ["line 0"],
            ["line 0", "line 1"],
            ["line 0", "line 1", "line 2"],
        ]
        assert [item["prompt"]["range_label"] for item in plan] == [
            "line 1",
            "lines 1-2",
            "lines 1-3",
        ]
        assert [item["prompt"]["chain_segment_ids"] for item in plan] == [
            [revision.segments[0].id],
            [revision.segments[0].id, revision.segments[1].id],
            [revision.segments[0].id, revision.segments[1].id, revision.segments[2].id],
        ]


def test_smart_plan_backward_chaining_uses_current_learned_prefix(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-backward-prefix", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(4)
        ]
        db.add(passage)
        db.flush()
        history = models.PracticeSession(revision_id=revision.id, plan={})
        db.add(history)
        db.flush()
        for index, segment in enumerate(revision.segments[:3]):
            item = models.PracticeItem(
                session_id=history.id,
                revision_id=revision.id,
                segment_id=segment.id,
                position=index,
                mode="cue_recall",
                prompt={},
            )
            db.add(item)
            db.flush()
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=2,
                )
            )
            for mode in ("cue_recall", "forward_chaining", "word_bank"):
                db.add(
                    models.Attempt(
                        session_id=history.id,
                        item_id=item.id,
                        segment_id=segment.id,
                        mode=mode,
                        rating="hesitant",
                        review_snapshot=[],
                    )
                )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        backward = [item for item in plan if item["mode"] == "backward_chaining"]
        assert [item["prompt"]["chain"] for item in backward] == [
            ["line 0", "line 1", "line 2"],
            ["line 1", "line 2"],
            ["line 2"],
        ]
        assert [item["prompt"]["range_label"] for item in backward] == [
            "lines 1-3",
            "lines 2-3",
            "line 3",
        ]


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


def test_smart_random_start_targets_are_not_presented_in_passage_order(
    monkeypatch: pytest.MonkeyPatch, session_factory: object
) -> None:
    def reverse(items: list[models.Segment]) -> None:
        items.reverse()

    monkeypatch.setattr(planning.random, "shuffle", reverse)
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-smart-random", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(4)
        ]
        db.add(passage)
        db.commit()
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
        random_items = [item for item in plan if item["mode"] == "random_start"]
        assert [item["prompt"]["target_text"] for item in random_items] == [
            "line 3",
            "line 2",
            "line 1",
            "line 0",
        ]
        assert plan[-1]["mode"] == "full_passage"


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


def test_smart_plan_serves_due_reviews_before_new_material(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-due", name="Ancient Greek")
        passage = models.Passage(title="Iliad 2", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        # Lines 0-1 are durable but NOT due; 2-3 are durable and overdue;
        # 4-13 are brand new. The cap holds 12, so something must lose.
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(14)
        ]
        db.add(passage)
        db.commit()
        for segment in revision.segments[:4]:
            overdue = segment.ordinal >= 2
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC) + timedelta(days=-1 if overdue else 30),
                    mastery_stage="durable",
                    clean_count=5,
                    attempt_count=6,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        ordinals = {segment.id: segment.ordinal for segment in revision.segments}
        planned = {ordinals[item["segment_id"]] for item in plan}
        # Overdue reviews outrank new material; not-yet-due maintenance loses.
        assert planned == set(range(2, 14))


def test_collection_smart_plan_shares_one_cap_across_revisions(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-collection-cap", name="Latin")
        passages = [
            models.Passage(title="Aeneid I", language_profile=language),
            models.Passage(title="Aeneid II", language_profile=language),
        ]
        revisions = [
            models.PassageRevision(passage=passage, revision_number=1, source_text="...")
            for passage in passages
        ]
        for revision in revisions:
            revision.segments = [
                models.Segment(kind="line", ordinal=index, text=f"line {index}")
                for index in range(8)
            ]
        db.add_all(passages)
        db.commit()

        plan = build_smart_plan_for_revisions(db, revisions, ["line"])
        assert len(plan) == 12
        assert {item["revision_id"] for item in plan} == {
            revisions[0].id,
            revisions[1].id,
        }


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


def test_prep_prompt_guides_japanese_token_readings() -> None:
    prompt = prep._prompt("Japanese", ["空こぼれ落ちたふたつの星が"])  # noqa: SLF001

    assert "leave blank for Japanese" in prompt
    assert "app attaches Japanese ruby readings locally" in prompt
    assert "for lines that include <words>" in prompt
    assert '<word index="0">空</word>' in prompt
    assert '<word index="1">こぼれ落ちた</word>' in prompt
    assert '<word index="2">ふたつ</word>' in prompt
    assert '<word index="4">星</word>' in prompt
    assert "Do not split Japanese into individual characters" in prompt
    assert "do not emit standalone punctuation tokens" in prompt
    assert "<text>空こぼれ落ちたふたつの星が</text>" in prompt


def test_prep_rejects_blank_token_readings() -> None:
    with pytest.raises(ValidationError):
        prep.TokenSuggestion(text="空", reading=" ", gloss="sky")


def test_create_revision_adds_local_japanese_tokens_with_kanji_ruby(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-local-ruby", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="空こぼれ落ちたふたつの星が",
                segments=[
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=0,
                        text="空こぼれ落ちたふたつの星が",
                        client_id="l0",
                    ),
                ],
            ),
        )

        tokens = sorted(
            (segment for segment in revision.segments if segment.kind == "token"),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == [
            "空",
            "こぼれ落ちた",
            "ふたつ",
            "の",
            "星",
            "が",
        ]
        readings = {
            token.text: [
                annotation.value
                for annotation in token.annotations
                if annotation.layer == "reading"
            ]
            for token in tokens
        }
        assert readings == {
            "空": ["そら"],
            "こぼれ落ちた": ["こぼれおちた"],
            "ふたつ": [],
            "の": [],
            "星": ["ほし"],
            "が": [],
        }


def test_create_revision_adds_local_japanese_juncture_tokens(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-juncture-ruby", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="空こぼれ落ちたふたつの星が\n光と闇の水面 吸い込まれてゆく",
                segments=[
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=0,
                        text="空こぼれ落ちたふたつの星が",
                        client_id="l0",
                    ),
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=1,
                        text="光と闇の水面 吸い込まれてゆく",
                        client_id="l1",
                    ),
                ],
            ),
        )

        juncture = next(segment for segment in revision.segments if segment.kind == "juncture")
        assert juncture.text == "光と闇 …"
        assert juncture.cue == "… の星が"
        tokens = sorted(
            (
                segment
                for segment in revision.segments
                if segment.parent_id == juncture.id and segment.kind == "token"
            ),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == [
            "光",
            "と",
            "闇",
        ]
        readings = {
            token.text: [
                annotation.value
                for annotation in token.annotations
                if annotation.layer == "reading"
            ]
            for token in tokens
        }
        assert readings == {
            "光": ["ひかり"],
            "と": [],
            "闇": ["やみ"],
        }


def test_create_revision_preserves_authored_japanese_token_readings(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-authored-ruby", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="その血の運命",
                segments=[
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=0,
                        text="その血の運命",
                        client_id="l0",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=1,
                        text="その",
                        parent_client_id="l0",
                        client_id="t0",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=2,
                        text="血",
                        parent_client_id="l0",
                        client_id="t1",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=3,
                        text="の",
                        parent_client_id="l0",
                        client_id="t2",
                    ),
                    schemas.SegmentInput(
                        kind="token",
                        ordinal=4,
                        text="運命",
                        parent_client_id="l0",
                        client_id="t3",
                        annotations=[
                            schemas.AnnotationInput(
                                layer="reading",
                                value="さだめ",
                                data={"render": "ruby"},
                            )
                        ],
                    ),
                ],
            ),
        )

        tokens = sorted(
            (segment for segment in revision.segments if segment.kind == "token"),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == ["その", "血", "の", "運命"]
        readings = {
            token.text: [
                annotation.value
                for annotation in token.annotations
                if annotation.layer == "reading"
            ]
            for token in tokens
        }
        assert readings == {"その": [], "血": ["ち"], "の": [], "運命": ["さだめ"]}


def test_retokenize_revision_preserves_existing_song_readings(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-retokenize-ruby", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        revision = models.PassageRevision(
            passage=passage,
            revision_number=1,
            source_text="光と闇の水面 吸い込まれてゆく",
        )
        line = models.Segment(
            id="line-retokenize",
            kind="line",
            ordinal=0,
            text="光と闇の水面 吸い込まれてゆく",
        )
        water = models.Segment(
            parent_id="line-retokenize",
            kind="token",
            ordinal=0,
            text="水面",
        )
        water.annotations = [
            models.Annotation(layer="reading", value="みなも", data={"render": "ruby"})
        ]
        revision.segments = [line, water]
        db.add(passage)
        db.flush()

        stats = furigana.retokenize_revision(db, revision)
        db.flush()
        db.expire(revision, ["segments"])

        assert stats["targets"] == 1
        tokens = sorted(
            (segment for segment in revision.segments if segment.kind == "token"),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == [
            "光",
            "と",
            "闇",
            "の",
            "水面",
            "吸い込まれてゆく",
        ]
        readings = {
            token.text: [
                annotation.value
                for annotation in token.annotations
                if annotation.layer == "reading"
            ]
            for token in tokens
        }
        assert readings["水面"] == ["みなも"]


def test_japanese_recall_prompt_uses_token_lead_in(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-recall-lead-in", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="空こぼれ落ちたふたつの星が",
                segments=[
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=0,
                        text="空こぼれ落ちたふたつの星が",
                        client_id="l0",
                    ),
                ],
            ),
        )
        line = next(segment for segment in revision.segments if segment.kind == "line")

        prompt = prompt_for("cue_recall", line, [line])

        assert prompt["lead_in"] == "空こぼれ落ちた"
        assert prompt["lead_in"] != line.text


def test_prep_backfills_japanese_ruby_without_llm(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-ruby-backfill", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        revision = models.PassageRevision(
            passage=passage,
            revision_number=1,
            source_text="空こぼれ落ちたふたつの星が",
        )
        revision.segments = [
            models.Segment(
                kind="line",
                ordinal=0,
                text="空こぼれ落ちたふたつの星が",
            )
        ]
        db.add(passage)
        db.commit()

        def should_not_generate(language_name: str, lines: list[str]) -> list[prep.LineSuggestion]:
            raise AssertionError("reading prep should not call the LLM")

        written = prep.suggest_prep(db, revision, ["reading"], generate=should_not_generate)
        assert written == {"reading": 3}

        tokens = sorted(
            (segment for segment in revision.segments if segment.kind == "token"),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == [
            "空",
            "こぼれ落ちた",
            "ふたつ",
            "の",
            "星",
            "が",
        ]


def test_prep_glosses_japanese_local_tokens(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="japanese-token-prep", name="Japanese")
        passage = models.Passage(title="Sono Chi no Sadame", language_profile=language)
        db.add(passage)
        db.flush()
        revision = create_revision(
            db,
            passage,
            schemas.RevisionInput(
                source_text="空こぼれ落ちたふたつの星が",
                segments=[
                    schemas.SegmentInput(
                        kind="line",
                        ordinal=0,
                        text="空こぼれ落ちたふたつの星が",
                        client_id="l0",
                    ),
                ],
            ),
        )

        def stub(language_name: str, lines: list[str]) -> list[prep.LineSuggestion]:
            assert language_name == "Japanese"
            assert lines == ["空こぼれ落ちたふたつの星が"]
            return [
                prep.LineSuggestion(
                    index=0,
                    cue="ふたつの星",
                    translation="Two stars spilled out from the sky",
                    glosses=[
                        prep.WordGloss(word_index=0, gloss="sky"),
                        prep.WordGloss(word_index=1, gloss="spill/fall"),
                        prep.WordGloss(word_index=2, gloss="two"),
                        prep.WordGloss(word_index=4, gloss="star"),
                    ],
                )
            ]

        written = prep.suggest_prep(
            db, revision, ["cue", "gloss", "translation", "reading"], generate=stub
        )
        assert written == {"cue": 1, "gloss": 4, "translation": 1, "reading": 0}

        db.expire_all()
        line = next(segment for segment in revision.segments if segment.kind == "line")
        assert line.cue == "ふたつの星"
        assert [(a.layer, a.value) for a in line.annotations] == [
            ("translation", "Two stars spilled out from the sky")
        ]

        tokens = sorted(
            (segment for segment in revision.segments if segment.kind == "token"),
            key=lambda segment: segment.ordinal,
        )
        assert [token.text for token in tokens] == [
            "空",
            "こぼれ落ちた",
            "ふたつ",
            "の",
            "星",
            "が",
        ]
        assert {
            token.text: [
                (annotation.layer, annotation.value, annotation.data)
                for annotation in token.annotations
            ]
            for token in tokens
        } == {
            "空": [
                ("reading", "そら", {"render": "ruby"}),
                ("gloss", "sky", {}),
            ],
            "こぼれ落ちた": [
                ("reading", "こぼれおちた", {"render": "ruby"}),
                ("gloss", "spill/fall", {}),
            ],
            "ふたつ": [
                ("gloss", "two", {}),
            ],
            "の": [],
            "星": [
                ("reading", "ほし", {"render": "ruby"}),
                ("gloss", "star", {}),
            ],
            "が": [],
        }

        assert prep.suggest_prep(
            db, revision, ["cue", "gloss", "translation", "reading"], generate=stub
        ) == {"cue": 0, "gloss": 0, "translation": 0, "reading": 0}


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


def test_minutes_budget_fills_short_passage_with_varied_repeats(
    session_factory: object,
) -> None:
    """A short passage cannot fill a generous budget in one pass, so leftover
    time buys extra repetitions that vary the retrieval mode rather than
    re-dealing the same exercise — and a per-segment cap stops a giant budget
    from grinding three lines to dust."""
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-fill", name="Latin")
        passage = models.Passage(title="Eclogue", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(3)
        ]
        db.add(passage)
        db.commit()

        # No budget: one quick pass, each new line exactly once.
        standard = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in standard] == ["progressive_fading"] * 3

        # 10 minutes (600s): the 3-line pass spends 3×75s = 225s, then the
        # broader rotation fills the rest in successive passage-order
        # run-throughs, tapering as the budget runs down.
        plan = build_smart_plan(db, revision, ["line"], minutes=10)
        assert [item["mode"] for item in plan] == (
            ["progressive_fading"] * 3
            + ["word_bank"] * 3
            + ["forward_chaining"] * 3
            + ["backward_chaining"] * 2
            + ["cue_recall"]
        )
        per_segment = {segment.id: [] for segment in revision.segments}
        for item in plan:
            per_segment[item["segment_id"]].append(item["mode"])
        assert sorted(len(modes) for modes in per_segment.values()) == [3, 4, 5]

        # A huge budget cannot exceed the per-segment repetition cap: still the
        # primary turn plus the five-mode rotation, never more.
        capped = build_smart_plan(db, revision, ["line"], minutes=120)
        assert len(capped) == 18


def test_minutes_fill_never_assigns_chaining_to_junctures(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-juncture-fill", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=0, text="line 0"),
            models.Segment(kind="juncture", ordinal=1, text="line 1 opening"),
            models.Segment(kind="line", ordinal=1, text="line 1"),
        ]
        db.add(passage)
        db.commit()

        plan = build_smart_plan(db, revision, None, minutes=120)
        juncture_id = revision.segments[1].id
        juncture_modes = {
            item["mode"] for item in plan if item["segment_id"] == juncture_id
        }
        assert juncture_modes.isdisjoint(
            {"forward_chaining", "backward_chaining", "word_bank"}
        )


def test_abandoned_sessions_expire_but_completed_history_does_not(
    session_factory: object,
) -> None:
    now = datetime.now(UTC)
    with session_factory() as db:  # type: ignore[operator]
        stale = models.PracticeSession(plan={}, updated_at=now - timedelta(hours=25))
        recent = models.PracticeSession(plan={}, updated_at=now - timedelta(hours=23))
        completed = models.PracticeSession(
            plan={},
            status="completed",
            updated_at=now - timedelta(days=7),
            completed_at=now - timedelta(days=7),
        )
        db.add_all([stale, recent, completed])
        db.commit()

        assert session_service.expire_stale_sessions(db, now) == 1
        assert stale.status == "expired"
        assert recent.status == "active"
        assert completed.status == "completed"


def test_meaning_recall_joins_only_graduated_translated_lines() -> None:
    exhausted = {
        "random_start": 1,
        "typed_recall": 1,
        "forward_chaining": 1,
        "backward_chaining": 1,
        "cue_recall": 1,
    }
    # Gates on a translation the way shadowing gates on reference audio.
    assert (
        smart_mode_for("review", difficult=False, mode_counts=exhausted, has_translation=True)
        == "meaning_recall"
    )
    assert (
        smart_mode_for("review", difficult=False, mode_counts=exhausted, has_translation=False)
        != "meaning_recall"
    )
    # Producing form from a semantic cue presumes the form is learned: the
    # learning stage never deals it, translation or not.
    assert (
        smart_mode_for("learning", difficult=False, has_translation=True) != "meaning_recall"
    )
    assert (
        smart_mode_for(
            "review", difficult=False, kind="juncture", mode_counts=exhausted, has_translation=True
        )
        != "meaning_recall"
    )


def test_juncture_recall_prompts_carry_the_previous_lines_audio_span(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-audio-cue", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        first = models.Segment(kind="line", ordinal=0, text="alpha beta gamma")
        juncture = models.Segment(
            kind="juncture",
            ordinal=1,
            text="delta epsilon …",
            cue="… beta gamma",
            metadata_json={"juncture_after": 0},
        )
        second = models.Segment(kind="line", ordinal=1, text="delta epsilon zeta")
        revision.segments = [first, juncture, second]
        db.add(passage)
        db.commit()
        asset = models.MediaAsset(
            revision_id=revision.id,
            category="reference",
            mime_type="audio/mpeg",
            original_name="teacher.mp3",
            storage_path="/dev/null",
            size_bytes=1,
            cue_points=[
                {"label": "line 1", "time": 0.0, "end": 4.2, "segment_id": first.id},
                {"label": "line 2", "time": 4.2, "end": 8.0, "segment_id": second.id},
            ],
        )
        db.add(asset)
        db.commit()

        plan = build_plan(db, revision, ["cue_recall"], None)
        prompts = {item["segment_id"]: item["prompt"] for item in plan}
        # Hearing the previous line is the performance condition: the juncture
        # card carries that line's span; line cards stay text-cued.
        assert prompts[juncture.id]["audio_cue"] == {
            "media_id": asset.id,
            "start": 0.0,
            "end": 4.2,
        }
        assert "audio_cue" not in prompts[first.id]
        assert "audio_cue" not in prompts[second.id]


def test_word_bank_deals_every_unit_out_of_order() -> None:
    line = models.Segment(kind="line", ordinal=0, text="arma virumque cano Troiae qui")
    prompt = prompt_for("word_bank", line, [line])
    units = line.text.split()
    # Every word is dealt exactly once, never in the natural order (the order
    # IS the thing being recalled), and the true line rides along as the
    # visual self-check answer.
    assert sorted(prompt["word_bank"]) == sorted(units)
    assert prompt["word_bank"] != units
    assert prompt["target_text"] == line.text


def test_typed_recall_is_a_written_recall_with_a_visual_check() -> None:
    line = models.Segment(kind="line", ordinal=0, text="arma virumque cano")
    prompt = prompt_for("typed_recall", line, [line])
    assert "type" in prompt["instruction"].lower()
    assert prompt["lead_in"] == "arma virumque"
    assert prompt["target_text"] == line.text

    # A typed juncture bridge names the exact word count, like its oral twin.
    juncture = models.Segment(
        kind="juncture", ordinal=1, text="epsilon zeta …", cue="… gamma delta"
    )
    bridge = prompt_for("typed_recall", juncture, [juncture])
    assert "type" in bridge["instruction"].lower()
    assert "first 2 words" in bridge["instruction"]
    assert bridge["lead_in"] == "… gamma delta"


def test_random_start_is_a_checkable_recall_with_an_endpoint() -> None:
    # The drop-in cold start must give something to recall (a lead-in, not the
    # whole line) plus the full line as the checkable answer, and an instruction
    # that states where to stop — not the old open-ended "continue".
    line = models.Segment(
        kind="line",
        ordinal=2,
        text="πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν",
        cue="souls to Hades",
    )
    prompt = prompt_for("random_start", line, [line])
    assert prompt["lead_in"] == "πολλὰς δ᾽"
    assert prompt["target_text"] == line.text
    assert "continue" not in prompt["instruction"].lower()
    assert "end" in prompt["instruction"].lower()


def test_every_mode_states_its_recitation_extent() -> None:
    # Each exercise must tell the learner how far to recite, phrased for what it
    # asks — no open-ended "continue". The expected endpoint phrase is pinned per
    # mode so the wording can't silently drift back to ambiguity.
    line = models.Segment(kind="line", ordinal=0, text="alpha beta gamma delta")
    following = models.Segment(kind="line", ordinal=1, text="epsilon zeta eta theta")
    context = [line, following]
    endpoint_phrase = {
        "shadowing": "line",
        "progressive_fading": "line",
        "word_bank": "then check",
        "forward_chaining": "then check",
        "backward_chaining": "then check",
        "cue_recall": "to the end",
        "typed_recall": "to the end",
        "meaning_recall": "to the end",
        "random_start": "to the end",
        "weak_link": "to the end",
        "full_passage": "start to finish",
        "recital": "start to finish",
    }
    for mode, needle in endpoint_phrase.items():
        instruction = prompt_for(mode, line, context)["instruction"].lower()
        assert needle in instruction, (mode, instruction)

    # A juncture stops mid-line, so its instruction must name the exact word
    # count, not a vague "opening". Two real words here -> "first 2 words".
    juncture = models.Segment(
        kind="juncture", ordinal=1, text="epsilon zeta …", cue="… gamma delta"
    )
    seam_instruction = prompt_for("cue_recall", juncture, [juncture])["instruction"].lower()
    assert "first 2 words" in seam_instruction, seam_instruction
    assert "stop" in seam_instruction
    # First exposure fades a juncture too; it must not claim a "whole line".
    fade_prompt = prompt_for("progressive_fading", juncture, [juncture])
    fade_instruction = fade_prompt["instruction"].lower()
    assert "opening" in fade_instruction, fade_instruction
    assert "whole line" not in fade_instruction
    # The tail→head association is what the card trains, so the previous
    # line's tail rides along as a persistent anchor; the final faded stage
    # must still identify which transition is being crossed. Lines need no
    # anchor — the card starts at full support, which names the line.
    assert fade_prompt["lead_in"] == "… gamma delta"
    assert "lead_in" not in prompt_for("progressive_fading", line, context)


def test_chaining_modes_explain_memory_range() -> None:
    line = models.Segment(kind="line", ordinal=0, text="alpha beta gamma delta")
    following = models.Segment(kind="line", ordinal=1, text="epsilon zeta eta theta")
    context = [line, following]

    for mode in ("forward_chaining", "backward_chaining"):
        prompt = prompt_for(mode, line, context, line_numbers=[1, 2])
        instruction = prompt["instruction"].lower()
        assert "from memory" in instruction, (mode, instruction)
        assert "lines 1-2" in instruction, (mode, instruction)
        assert prompt["range_label"] == "lines 1-2"
        assert prompt["line_start"] == 1
        assert prompt["line_end"] == 2
        assert prompt["chain_segment_ids"] == [line.id, following.id]


def test_both_failure_ratings_schedule_as_lapses() -> None:
    # "incorrect" means errors in verbatim recall — a failed card. Scheduling
    # it as FSRS Hard (a pass) would extend the interval on exactly the lines
    # that need reps; only the ladder distinguishes the two failure kinds.
    assert RATING_MAP["revealed"] == Rating.Again
    assert RATING_MAP["incorrect"] == Rating.Again
    assert RATING_MAP["hesitant"] == Rating.Good
    assert RATING_MAP["clean"] == Rating.Easy


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


def test_recall_prompt_uses_verbatim_lead_in() -> None:
    # Line 5 of the Iliad: the lead-in must be the exact opening words, and the
    # elided particle δ᾽ must survive in the full answer (no LLM paraphrase).
    line = models.Segment(
        kind="line",
        ordinal=27,
        text="οἰωνοῖσί τε πᾶσι, Διὸς δ᾽ ἐτελείετο βουλή,",
        cue="Διὸς ἐτελείετο βουλή",
    )
    cue = prompt_for("cue_recall", line, [line])
    assert cue["lead_in"] == "οἰωνοῖσί τε"
    assert cue["target_text"] == line.text
    assert "δ᾽" in cue["target_text"]
    # The evocative phrase is demoted to an optional hint, not the prompt.
    assert cue["hint"] == "Διὸς ἐτελείετο βουλή"

    weak = prompt_for("weak_link", line, [line])
    assert weak["lead_in"] == "οἰωνοῖσί τε"

    # A juncture already reads as "previous tail → next head", so its own cue is
    # the lead-in and its text is the answer.
    juncture = models.Segment(
        kind="juncture",
        ordinal=6,
        text="οὐλομένην, ἣ μῡρί᾽ …",
        cue="… θεὰ Πηληϊάδεω Ἀχιλῆος",
    )
    seam = prompt_for("cue_recall", juncture, [juncture])
    assert seam["lead_in"] == "… θεὰ Πηληϊάδεω Ἀχιλῆος"
    assert seam["target_text"] == "οὐλομένην, ἣ μῡρί᾽ …"


def test_practice_plan_prefers_personal_note_over_revision_cue(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-personal-note", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="Διὸς δ᾽ ἐτελείετο βουλή"
        )
        line = models.Segment(
            kind="line",
            ordinal=0,
            text="Διὸς δ᾽ ἐτελείετο βουλή",
            cue="the will of Zeus",
        )
        revision.segments = [line]
        db.add(passage)
        db.commit()
        db.add(models.PersonalNote(segment_id=line.id, text="boulē → tabouleh"))
        db.commit()

        plan = build_plan(db, revision, ["cue_recall"], ["line"])

        assert plan[0]["prompt"]["hint"] == "boulē → tabouleh"
        assert line.cue == "the will of Zeus"


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
