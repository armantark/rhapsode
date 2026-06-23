import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from rhapsode import models, schemas
from rhapsode.services import planning, prep
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
from rhapsode.services.scheduling import _next_clean_streak, mastery_stage


def test_progressive_masks_remove_support() -> None:
    masks = progressive_masks("arma virumque cano")
    assert masks == [
        "arma virumque cano",
        "… virumque cano",
        "… cano",
        "…",
    ]


def test_progressive_masks_handle_no_space_scripts_gradually() -> None:
    masks = progressive_masks("空こぼれ落ちた")

    assert masks == [
        "空こぼれ落ちた",
        "…ぼれ落ちた",
        "…落ちた",
        "…ちた",
        "…",
    ]


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
    assert smart_mode_for("learning", difficult=False) == "cue_recall"
    assert smart_mode_for("review", difficult=False) == "random_start"
    assert smart_mode_for("durable", difficult=False) == "random_start"
    # Difficulty pulls a segment into weak-link drilling, but a brand-new
    # segment still needs scaffolding before being drilled cold.
    assert smart_mode_for("review", difficult=True) == "weak_link"
    assert smart_mode_for(None, difficult=True) == "progressive_fading"
    # Once a technique has been used, the coach deliberately introduces the
    # least-practiced useful exercise instead of repeating the same label.
    assert (
        smart_mode_for("learning", difficult=False, mode_counts={"cue_recall": 1})
        == "forward_chaining"
    )
    assert (
        smart_mode_for(
            "review",
            difficult=True,
            mode_counts={"weak_link": 5, "random_start": 1},
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
            for mode in ("cue_recall", "progressive_fading"):
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
    assert '<word index="1">こぼれ落ち</word>' in prompt
    assert '<word index="2">た</word>' in prompt
    assert '<word index="6">星</word>' in prompt
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
            "こぼれ落ち",
            "た",
            "ふた",
            "つ",
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
            "こぼれ落ち": ["こぼれおち"],
            "た": [],
            "ふた": [],
            "つ": [],
            "の": [],
            "星": ["ほし"],
            "が": [],
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
            "こぼれ落ち",
            "た",
            "ふた",
            "つ",
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
                        prep.WordGloss(word_index=3, gloss="two"),
                        prep.WordGloss(word_index=6, gloss="star"),
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
            "こぼれ落ち",
            "た",
            "ふた",
            "つ",
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
            "こぼれ落ち": [
                ("reading", "こぼれおち", {"render": "ruby"}),
                ("gloss", "spill/fall", {}),
            ],
            "た": [],
            "ふた": [
                ("gloss", "two", {}),
            ],
            "つ": [],
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
        # run-throughs. The final random-start turn fits for only one line.
        plan = build_smart_plan(db, revision, ["line"], minutes=10)
        assert [item["mode"] for item in plan] == (
            ["progressive_fading"] * 3
            + ["forward_chaining"] * 3
            + ["backward_chaining"] * 3
            + ["cue_recall"] * 3
            + ["random_start"]
        )
        per_segment = {segment.id: [] for segment in revision.segments}
        for item in plan:
            per_segment[item["segment_id"]].append(item["mode"])
        assert sorted(len(modes) for modes in per_segment.values()) == [4, 4, 5]

        # A huge budget cannot exceed the per-segment repetition cap: still the
        # primary turn plus the four-mode rotation, never more.
        capped = build_smart_plan(db, revision, ["line"], minutes=120)
        assert len(capped) == 15


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
        assert juncture_modes.isdisjoint({"forward_chaining", "backward_chaining"})


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
        "forward_chaining": "last line",
        "backward_chaining": "ending",
        "cue_recall": "to the end",
        "random_start": "to the end",
        "weak_link": "to the end",
        "full_passage": "start to finish",
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
    fade_instruction = prompt_for("progressive_fading", juncture, [juncture])["instruction"].lower()
    assert "opening" in fade_instruction, fade_instruction
    assert "whole line" not in fade_instruction


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
