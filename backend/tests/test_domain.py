import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fsrs import Card, Rating
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rhapsode import models, schemas
from rhapsode.services import furigana, planning, prep
from rhapsode.services import sessions as session_service
from rhapsode.services.backup import (
    SNAPSHOT_RETENTION,
    snapshot_sqlite,
    startup_snapshot,
)
from rhapsode.services.passages import create_revision, merge_passages
from rhapsode.services.planning import (
    BUILT_IN_MODES,
    _difficult_segment_ids,
    build_plan,
    build_smart_plan,
    build_smart_plan_for_revisions,
    learning_scaffold_steps,
    learning_step_successes_required,
    progressive_masks,
    prompt_for,
    register_practice_mode,
    smart_mode_for,
)
from rhapsode.services.scheduling import (
    RATING_MAP,
    _next_clean_streak,
    mastery_stage,
    review_segment,
)


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


def test_learning_scaffold_is_five_spaced_phases() -> None:
    line = models.Segment(
        kind="line",
        ordinal=0,
        text="one two three four five six seven eight",
    )

    steps = learning_scaffold_steps(line)

    assert [step["kind"] for step in steps] == [
        "chunk",
        "fade_tail",
        "fade_front",
        "half_words",
        "initials",
    ]
    assert steps[0]["target_levels"] == [
        "one two three",
        "one two three four five six",
        line.text,
    ]
    assert steps[0]["required_successes"] == 3
    assert steps[1]["cue_levels"][0].startswith("one two three")
    assert steps[1]["cue_levels"][-1].startswith("one two")
    assert steps[2]["cue_levels"][0].startswith("•••")
    assert steps[2]["cue_levels"][-1].endswith("seven eight")
    assert steps[3]["cue_levels"] == ["on… tw… thr… fo… fi… si… sev… eig…"]
    assert steps[4]["cue_levels"] == ["o. t. t. f. f. s. s. e."]


def test_learning_scaffold_keeps_combining_macrons_attached_to_greek_cues() -> None:
    line = models.Segment(kind="line", ordinal=0, text="ψῡχὰ̄ς θεὰ̄ ᾱρα")

    steps = learning_scaffold_steps(line)

    assert steps[3]["cue_levels"] == ["ψῡχ… θε… ᾱρ…"]
    assert steps[4]["cue_levels"] == ["ψ. θ. ᾱ."]


def test_learning_scaffold_keeps_every_phase_usable_for_one_unit() -> None:
    line = models.Segment(kind="line", ordinal=0, text="arma")

    steps = learning_scaffold_steps(line)

    assert all(step["cue_levels"] for step in steps)


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
    assert smart_mode_for(None, difficult=False) == "acquisition"
    assert smart_mode_for("new", difficult=False) == "acquisition"
    assert smart_mode_for(None, difficult=False, kind="juncture") == "progressive_fading"
    # Learning lines rebuild order first (word bank), then produce (cue recall).
    assert smart_mode_for("learning", difficult=False) == "word_bank"
    assert smart_mode_for("review", difficult=False) == "typed_recall"
    assert smart_mode_for("durable", difficult=False) == "typed_recall"
    # Graduated lines earn the typed check without an automatic cold-start
    # card; the rotation holds only single-line lead-in modes, because chains
    # are run-throughs and run-throughs are the warmup and the finisher.
    assert (
        smart_mode_for("review", difficult=False, mode_counts={"typed_recall": 1})
        == "cue_recall"
    )
    # Difficulty pulls a segment into weak-link drilling, but a brand-new
    # segment still needs scaffolding before being drilled cold.
    assert smart_mode_for("review", difficult=True) == "weak_link"
    assert smart_mode_for(None, difficult=True) == "acquisition"
    # A recent lapse on already-acquired material restores support instead of
    # sending it straight into cold weak-link recall.
    assert (
        smart_mode_for(
            "learning",
            difficult=True,
            acquisition_succeeded=True,
            last_rating="incorrect",
        )
        == "word_bank"
    )
    assert (
        smart_mode_for(
            "learning",
            difficult=True,
            kind="juncture",
            acquisition_succeeded=True,
            last_rating="revealed",
        )
        == "progressive_fading"
    )
    # The first return after a successful acquisition is a clean cue-only
    # retrieval regardless of the grade; passage flow belongs to the warmup
    # and finisher chains, never to a per-line review card.
    assert (
        smart_mode_for(
            "learning",
            difficult=False,
            acquisition_succeeded=True,
            last_mode="acquisition",
            last_rating="hesitant",
        )
        == "cue_recall"
    )
    assert (
        smart_mode_for(
            "learning",
            difficult=False,
            acquisition_succeeded=True,
            last_mode="acquisition",
            last_rating="clean",
        )
        == "cue_recall"
    )
    # Once a technique has been used, the coach deliberately introduces the
    # least-practiced useful exercise instead of repeating the same label.
    assert (
        smart_mode_for(
            "learning", difficult=False, mode_counts={"word_bank": 1, "cue_recall": 1}
        )
        == "progressive_fading"
    )
    assert (
        smart_mode_for(
            "review",
            difficult=True,
            mode_counts={"weak_link": 5, "typed_recall": 1},
        )
        == "cue_recall"
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


def test_smart_plan_opens_with_a_warmup_chain_over_the_mastered_tail(
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
        # Warmup → work → cooldown: one chain over the mastered tail opens the
        # session, reviews stay single-line lead-in modes (chains left the
        # rotation — a chain is a run-through, and run-throughs are warmup and
        # finisher), and the holistic close still ends it.
        # These mastered rows still sit in stage "learning" (clean streak
        # below the review threshold), so the single-line rotation deals its
        # gentlest production step rather than the graduated typed check.
        assert [item["mode"] for item in plan] == [
            "forward_chaining",
            "word_bank",
            "word_bank",
            "word_bank",
            "full_passage",
        ]
        warmup = plan[0]
        # The whole prefix fits in the warmup, so it starts at line 1 and
        # needs no lead-in anchor.
        assert "lead_in" not in warmup["prompt"]
        assert warmup["segment_id"] == revision.segments[2].id
        assert warmup["prompt"]["chain"] == ["line 0", "line 1", "line 2"]
        assert warmup["prompt"]["range_label"] == "lines 1-3 in this passage"
        assert warmup["prompt"]["chain_segment_ids"] == [
            revision.segments[0].id,
            revision.segments[1].id,
            revision.segments[2].id,
        ]
        assert [item["segment_id"] for item in plan[1:-1]] == [
            segment.id for segment in revision.segments
        ]


def test_smart_plan_restores_support_after_recent_acquired_lapse(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-lapse-support", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="arma virumque cano"
        )
        line = models.Segment(kind="line", ordinal=0, text="arma virumque cano")
        revision.segments = [line]
        db.add(passage)
        db.flush()
        history = models.PracticeSession(revision_id=revision.id, plan={})
        db.add(history)
        db.flush()
        item = models.PracticeItem(
            session_id=history.id,
            revision_id=revision.id,
            segment_id=line.id,
            position=0,
            mode="cue_recall",
            prompt={},
            completed=True,
        )
        db.add(item)
        db.flush()
        db.add_all(
            [
                models.ReviewState(
                    segment_id=line.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=3,
                    acquisition_succeeded=True,
                ),
                models.Attempt(
                    session_id=history.id,
                    item_id=item.id,
                    segment_id=line.id,
                    mode="cue_recall",
                    rating="incorrect",
                    review_snapshot=[],
                ),
            ]
        )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])

        assert [planned["mode"] for planned in plan] == ["word_bank"]


def test_backward_chaining_is_manual_only_and_chains_to_the_passage_end(
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

        # Chains left the automatic rotation entirely — a smart session's only
        # chains are the warmup and the finisher, both forward.
        plan = build_smart_plan(db, revision, ["line"])
        assert all(item["mode"] != "backward_chaining" for item in plan)

        # The mode itself survives for manual sessions, chaining each start
        # point through to the end of the passage.
        manual = build_plan(db, revision, ["backward_chaining"], ["line"])
        assert [item["prompt"]["chain"] for item in manual] == [
            ["line 0", "line 1", "line 2", "line 3"],
            ["line 1", "line 2", "line 3"],
            ["line 2", "line 3"],
            ["line 3"],
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

        # Fresh lines receive the composite first lesson, no finisher yet.
        plan = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in plan] == ["acquisition", "acquisition"]

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
            "forward_chaining",
            "typed_recall",
            "typed_recall",
            "full_passage",
        ]


def test_smart_plan_never_deals_random_start_and_preserves_passage_order(
    session_factory: object,
) -> None:
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
        assert all(item["mode"] != "random_start" for item in plan)
        assert plan[0]["mode"] == "forward_chaining"
        assert [item["segment_id"] for item in plan[1:-1]] == [
            segment.id for segment in revision.segments
        ]
        assert plan[-1]["mode"] == "full_passage"


def test_smart_plan_window_supersedes_out_of_order_triage_history(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-epic", name="Ancient Greek")
        passage = models.Passage(title="Iliad 1", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        # Old triage introduced late lines out of order. They remain locked
        # because the first three non-mastered positions define the runway.
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(8)
        ]
        db.add(passage)
        db.commit()
        for segment in revision.segments[5:]:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                    acquisition_succeeded=True,
                    learning_step=0,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        assert len(plan) == 3
        ordinals = {segment.id: segment.ordinal for segment in revision.segments}
        planned_ordinals = [ordinals[item["segment_id"]] for item in plan]
        assert planned_ordinals == [0, 1, 2]
        assert {5, 6, 7}.isdisjoint(planned_ordinals)


def test_linear_window_one_deals_one_consecutive_guided_block(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-window-one", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(5)
        ]
        db.add(passage)
        db.flush()
        db.add(models.AppSetting(key="linear_window", value=1))
        db.add(
            models.ReviewState(
                segment_id=revision.segments[0].id,
                fsrs_card_json="{}",
                due_at=datetime.now(UTC) + timedelta(days=30),
                mastery_stage="review",
                clean_count=2,
                attempt_count=2,
                acquisition_succeeded=True,
                learning_step=None,
            )
        )
        db.add(
            models.ReviewState(
                segment_id=revision.segments[1].id,
                fsrs_card_json="{}",
                due_at=datetime.now(UTC),
                mastery_stage="learning",
                clean_count=0,
                attempt_count=1,
                acquisition_succeeded=True,
                learning_step=0,
            )
        )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        # The single mastered (not-due) line still opens the session as a
        # one-line warmup recall before the frontier's guided block.
        assert [item["segment_id"] for item in plan] == [
            revision.segments[0].id,
            *[revision.segments[1].id] * 3,
        ]
        assert [item["mode"] for item in plan] == ["cue_recall", *["guided_recall"] * 3]
        assert all(
            item["segment_id"] not in {line.id for line in revision.segments[2:]}
            for item in plan
        )


def test_default_window_deals_three_line_blocks_without_crossing_locked_tail(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-window-blocks", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(5)
        ]
        db.add(passage)
        db.flush()
        for line in revision.segments[:3]:
            db.add(
                models.ReviewState(
                    segment_id=line.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                    acquisition_succeeded=True,
                    learning_step=0,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, ["line"])
        assert [item["segment_id"] for item in plan] == [
            line.id for line in revision.segments[:3] for _ in range(3)
        ]
        assert {item["mode"] for item in plan} == {"guided_recall"}


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
        # The warmup chain opens on the mastered tail, due mastered lines
        # lead the work, followed by all three window lines. The
        # mastered-prefix finisher closes the session, credited to the NEWEST
        # mastered line so line 1's rotation is not permanently skewed;
        # not-due maintenance is no longer used to backfill.
        assert planned == {2, 3, 4, 5, 6}
        assert plan[0]["mode"] == "forward_chaining"
        assert ordinals[plan[0]["segment_id"]] == 3
        # A warmup that starts mid-passage (prefix is 4 lines, tail covers
        # 2-4) anchors on the preceding line's tail so the entry is cued.
        assert plan[0]["prompt"]["lead_in"] == "line 0"
        assert [ordinals[item["segment_id"]] for item in plan[1:6]] == [2, 3, 4, 5, 6]
        assert plan[-1]["mode"] == "forward_chaining"
        assert ordinals[plan[-1]["segment_id"]] == 3


def test_cap_reserves_room_for_the_finisher(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-cap-reserve", name="Latin")
        passage = models.Passage(title="Metamorphoses", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(14)
        ]
        db.add(passage)
        db.commit()
        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC) - timedelta(hours=1),
                    mastery_stage="durable",
                    clean_count=5,
                    attempt_count=6,
                    acquisition_succeeded=True,
                    learning_step=None,
                )
            )
        db.commit()

        # Fourteen due mastered lines exceed the 12-item cap: the finisher must
        # be reserved a slot rather than truncated away, so the session is 11
        # reviews plus the holistic close.
        plan = build_smart_plan(db, revision, ["line"])
        assert len(plan) == 12
        assert plan[-1]["mode"] == "full_passage"
        assert all(item["mode"] != "full_passage" for item in plan[:-1])


def test_collection_window_spans_revisions_in_member_order(session_factory: object) -> None:
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
                for index in range(4)
            ]
        db.add_all(passages)
        db.commit()
        for segment in revisions[0].segments[:3]:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC) + timedelta(days=30),
                    mastery_stage="review",
                    clean_count=2,
                    attempt_count=2,
                    acquisition_succeeded=True,
                    learning_step=None,
                )
            )
        db.commit()

        plan = build_smart_plan_for_revisions(db, revisions, ["line"])
        # The warmup chain comes from the last member with a mastered prefix.
        assert plan[0]["mode"] == "forward_chaining"
        assert plan[0]["segment_id"] == revisions[0].segments[2].id
        expected_window = [
            revisions[0].segments[3].id,
            revisions[1].segments[0].id,
            revisions[1].segments[1].id,
        ]
        assert [item["segment_id"] for item in plan[1:4]] == expected_window
        assert all(item["mode"] == "acquisition" for item in plan[1:4])
        assert plan[-1]["mode"] == "forward_chaining"
        assert {
            revisions[1].segments[2].id,
            revisions[1].segments[3].id,
        }.isdisjoint({item["segment_id"] for item in plan})


def _mastered_state(segment_id: str, *, due: bool) -> models.ReviewState:
    return models.ReviewState(
        segment_id=segment_id,
        fsrs_card_json="{}",
        due_at=datetime.now(UTC) + timedelta(days=-1 if due else 30),
        mastery_stage="review",
        clean_count=2,
        attempt_count=2,
        acquisition_succeeded=True,
        learning_step=None,
    )


def _scope_revision(db: Session, slug: str, count: int) -> models.PassageRevision:
    language = models.LanguageProfile(slug=slug, name="Latin")
    passage = models.Passage(title="Aeneid", language_profile=language)
    revision = models.PassageRevision(passage=passage, revision_number=1, source_text="...")
    revision.segments = [
        models.Segment(kind="line", ordinal=index, text=f"line {index}")
        for index in range(count)
    ]
    db.add(passage)
    db.flush()
    return revision


def test_line_scope_opens_the_window_inside_the_picked_range(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        revision = _scope_revision(db, "latin-scope-window", 10)
        db.commit()

        # The scope is the whole world: the window is the first W unmastered
        # lines WITHIN lines 5-8, not the passage's own frontier at line 1.
        plan = build_smart_plan(db, revision, ["line"], line_scope=(5, 8))
        ordinals = {segment.id: segment.ordinal for segment in revision.segments}
        assert [ordinals[item["segment_id"]] for item in plan] == [4, 5, 6]
        assert {item["mode"] for item in plan} == {"acquisition"}


def test_line_scope_keeps_due_reviews_inside_the_range(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        revision = _scope_revision(db, "latin-scope-reviews", 8)
        for segment in revision.segments:
            db.add(_mastered_state(segment.id, due=True))
        db.commit()

        # Every line is mastered and overdue, so only the scope decides which
        # reviews are dealt.
        plan = build_smart_plan(db, revision, ["line"], line_scope=(4, 6))
        ordinals = {segment.id: segment.ordinal for segment in revision.segments}
        assert {ordinals[item["segment_id"]] for item in plan} == {3, 4, 5}
        # The scope is fully mastered, so it closes on its own holistic recital
        # rather than a partial chain.
        assert plan[-1]["mode"] == "full_passage"
        # Line numbers stay absolute so the card names the passage's own lines.
        assert plan[-1]["prompt"]["range_label"] == "lines 4-6 in this passage"


def test_line_scope_gates_junctures_at_its_edges(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-scope-juncture", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        lines = [
            models.Segment(kind="line", ordinal=index, text=f"line {index}")
            for index in range(4)
        ]
        junctures = [
            models.Segment(
                kind="juncture",
                ordinal=index,
                text=f"line {index} opening",
                metadata_json={"juncture_after": index - 1},
            )
            for index in range(1, 4)
        ]
        revision.segments = [*lines, *junctures]
        db.add(passage)
        db.flush()
        for line in lines:
            db.add(_mastered_state(line.id, due=False))
        db.commit()

        plan = build_smart_plan(db, revision, None, line_scope=(3, 4))
        planned = {item["segment_id"] for item in plan}
        # Only the seam whose BOTH flanks sit inside lines 3-4 survives; the
        # one landing on line 3 from the line before the scope does not.
        assert junctures[2].id in planned
        assert {junctures[0].id, junctures[1].id}.isdisjoint(planned)


def test_scoped_warmup_anchors_on_the_line_before_the_range(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        revision = _scope_revision(db, "latin-scope-warmup", 6)
        for segment in revision.segments[:5]:
            db.add(_mastered_state(segment.id, due=False))
        db.commit()

        plan = build_smart_plan(db, revision, ["line"], line_scope=(3, 6))
        ordinals = {segment.id: segment.ordinal for segment in revision.segments}
        # The warmup chains the scope's own mastered prefix (lines 3-5), and
        # cues its mid-passage entry with the tail of line 2 — the line just
        # OUTSIDE the scope, which is exactly what a runner needs to start.
        assert plan[0]["mode"] == "forward_chaining"
        assert ordinals[plan[0]["segment_id"]] == 4
        assert plan[0]["prompt"]["lead_in"] == "line 1"
        assert plan[0]["prompt"]["line_start"] == 3
        # Line 6 is the scope's frontier; lines 1-2 stay out of the session.
        assert ordinals[plan[1]["segment_id"]] == 5
        assert {0, 1}.isdisjoint({ordinals[item["segment_id"]] for item in plan})


def test_line_range_must_be_an_ordered_pair_on_a_smart_session() -> None:
    assert schemas.SessionCreate(revision_id="rev", line_start=2, line_end=5).line_end == 5
    with pytest.raises(ValidationError):
        schemas.SessionCreate(revision_id="rev", line_start=5, line_end=2)
    with pytest.raises(ValidationError):
        schemas.SessionCreate(revision_id="rev", line_start=2)
    with pytest.raises(ValidationError):
        schemas.SessionCreate(revision_id="rev", line_start=0, line_end=2)
    with pytest.raises(ValidationError):
        schemas.SessionCreate(
            revision_id="rev",
            line_start=1,
            line_end=2,
            modes=[schemas.PracticeMode.cue_recall],
        )


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


def test_merge_passages_stitches_progress_onto_the_host(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-merge", name="Ancient Greek")
        host = models.Passage(title="Iliad 1-2", language_profile=language)
        source = models.Passage(title="Iliad 3-4", language_profile=language)
        db.add_all([host, source])
        db.flush()

        def lines(*texts: str, labels: list[str] | None = None) -> list[schemas.SegmentInput]:
            return [
                schemas.SegmentInput(
                    kind="line",
                    ordinal=index,
                    text=text,
                    reference_label=(labels or [None] * len(texts))[index],
                )
                for index, text in enumerate(texts)
            ]

        host_revision = create_revision(
            db,
            host,
            schemas.RevisionInput(
                source_text="one two three\nfour five six",
                segments=lines(
                    "one two three", "four five six", labels=["Iliad 1.1", "Iliad 1.2"]
                ),
            ),
        )
        source_segments = lines(
            "seven eight nine", "ten eleven twelve", labels=["Iliad 1.3", "Iliad 1.4"]
        )
        # Token children ride along under their line; the merge must keep the
        # parent linkage (unshifted child ordinals once orphaned these into
        # top-level word-soup segments).
        source_segments[0] = source_segments[0].model_copy(update={"client_id": "l0"})
        source_segments.extend(
            schemas.SegmentInput(
                kind="token",
                ordinal=index + 1,
                text=word,
                parent_client_id="l0",
                annotations=[
                    schemas.AnnotationInput(layer="gloss", value=f"g-{word}", data={})
                ],
            )
            for index, word in enumerate(["seven", "eight", "nine"])
        )
        source_revision = create_revision(
            db,
            source,
            schemas.RevisionInput(
                source_text="seven eight nine\nten eleven twelve",
                segments=source_segments,
            ),
        )
        host_lines = sorted(
            (s for s in host_revision.segments if s.kind == "line"),
            key=lambda s: s.ordinal,
        )
        source_lines = sorted(
            (s for s in source_revision.segments if s.kind == "line"),
            key=lambda s: s.ordinal,
        )
        source_juncture = next(
            s for s in source_revision.segments if s.kind == "juncture"
        )

        def add_state(segment_id: str, step: int | None, successes: int = 0) -> None:
            db.add(
                models.ReviewState(
                    segment_id=segment_id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC) + timedelta(days=7),
                    mastery_stage="review" if step is None else "learning",
                    clean_count=2 if step is None else 0,
                    attempt_count=3,
                    acquisition_succeeded=True,
                    learning_step=step,
                    learning_success_count=successes,
                )
            )

        for line in host_lines:
            add_state(line.id, None)
        add_state(source_lines[0].id, None)
        add_state(source_lines[1].id, 1, successes=2)
        add_state(source_juncture.id, None)
        history = models.PracticeSession(revision_id=source_revision.id, plan={})
        db.add(history)
        db.flush()
        item = models.PracticeItem(
            session_id=history.id,
            revision_id=source_revision.id,
            segment_id=source_lines[0].id,
            position=0,
            mode="cue_recall",
            prompt={},
        )
        db.add(item)
        db.flush()
        db.add(
            models.Attempt(
                session_id=history.id,
                item_id=item.id,
                segment_id=source_lines[0].id,
                mode="cue_recall",
                rating="clean",
                review_snapshot=[],
            )
        )
        db.add(models.PersonalNote(segment_id=source_lines[1].id, text="boulē → tabouleh"))
        db.add(
            models.MediaAsset(
                revision_id=source_revision.id,
                category="reference",
                mime_type="audio/mpeg",
                original_name="teacher.mp3",
                storage_path="media/teacher.mp3",
                size_bytes=1,
                cue_points=[{"segment_id": source_lines[0].id, "time": 0.0, "end": 2.5}],
            )
        )
        collection = models.Collection(name="Iliad thus far")
        db.add(collection)
        db.flush()
        db.add(
            models.CollectionPassage(
                collection_id=collection.id, passage_id=host.id, position=0
            )
        )
        db.add(
            models.CollectionPassage(
                collection_id=collection.id, passage_id=source.id, position=1
            )
        )
        db.commit()

        moved = merge_passages(db, host, [source])
        assert moved["lines"] == 2 and moved["states"] == 3

        merged = db.get(models.PassageRevision, host.active_revision_id)
        assert merged is not None
        merged_lines = sorted(
            (s for s in merged.segments if s.kind == "line"), key=lambda s: s.ordinal
        )
        assert [line.text for line in merged_lines] == [
            "one two three",
            "four five six",
            "seven eight nine",
            "ten eleven twelve",
        ]
        assert [line.reference_label for line in merged_lines] == [
            "Iliad 1.1",
            "Iliad 1.2",
            "Iliad 1.3",
            "Iliad 1.4",
        ]
        # The host's own rows and states were never touched.
        assert [line.id for line in merged_lines[:2]] == [line.id for line in host_lines]

        states = {
            state.segment_id: state
            for state in db.scalars(select(models.ReviewState))
        }
        # Progress rode along: the mid-ladder line keeps its exact rung.
        moved_line = merged_lines[3]
        assert states[moved_line.id].learning_step == 1
        assert states[moved_line.id].learning_success_count == 2
        assert source_lines[1].id not in states

        junctures = sorted(
            (s for s in merged.segments if s.kind == "juncture"),
            key=lambda s: s.ordinal,
        )
        assert len(junctures) == 3
        # The former seam juncture (1.2 → 1.3) is brand new and ungated state-
        # free; the source's internal juncture kept its state.
        seam, internal = junctures[1], junctures[2]
        assert seam.cue is not None and "five six" in seam.cue
        assert seam.id not in states
        assert internal.id in states

        # Token children stay parented under their merged line — never orphaned
        # to the top level — and keep their annotations.
        merged_tokens = [
            s for s in merged.segments if s.kind == "token"
        ]
        assert len(merged_tokens) == 3
        assert all(token.parent_id == merged_lines[2].id for token in merged_tokens)
        assert {a.value for token in merged_tokens for a in token.annotations} == {
            "g-seven",
            "g-eight",
            "g-nine",
        }

        attempt = db.scalar(select(models.Attempt))
        assert attempt is not None and attempt.segment_id == merged_lines[2].id
        note = db.scalar(select(models.PersonalNote))
        assert note is not None and note.segment_id == merged_lines[3].id
        asset = db.scalar(select(models.MediaAsset))
        assert asset is not None
        assert asset.revision_id == merged.id
        assert asset.cue_points == [
            {"segment_id": merged_lines[2].id, "time": 0.0, "end": 2.5}
        ]

        members = list(db.scalars(select(models.CollectionPassage)))
        assert [(member.passage_id, member.position) for member in members] == [
            (host.id, 0)
        ]
        assert source.description is not None and "Merged into" in source.description
        with pytest.raises(ValueError, match="already merged"):
            merge_passages(db, host, [source])


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

        # A fresh passage deals only its lines: the juncture waits until both
        # flanks have completed the guided ladder.
        plan = build_smart_plan(db, revision, None)
        kinds = {s.id: s.kind for s in revision.segments}
        planned = [kinds[item["segment_id"]] for item in plan]
        assert planned == ["line", "line"]

        lines = sorted(
            (segment for segment in revision.segments if segment.kind == "line"),
            key=lambda segment: segment.ordinal,
        )
        db.add(
            models.ReviewState(
                segment_id=lines[0].id,
                fsrs_card_json="{}",
                due_at=datetime.now(UTC) + timedelta(days=30),
                mastery_stage="review",
                clean_count=2,
                attempt_count=2,
                acquisition_succeeded=True,
                learning_step=None,
            )
        )
        db.commit()
        plan = build_smart_plan(db, revision, None)
        assert junctures[0].id not in {item["segment_id"] for item in plan}

        db.add(
            models.ReviewState(
                segment_id=lines[1].id,
                fsrs_card_json="{}",
                due_at=datetime.now(UTC) + timedelta(days=30),
                mastery_stage="review",
                clean_count=2,
                attempt_count=2,
                acquisition_succeeded=True,
                learning_step=None,
            )
        )
        db.commit()
        plan = build_smart_plan(db, revision, None)
        planned = [kinds[item["segment_id"]] for item in plan]
        # Warmup chain over the mastered pair, the unlocked juncture, then the
        # holistic close.
        assert planned == ["line", "juncture", "line"]
        assert plan[0]["mode"] == "forward_chaining"
        assert plan[-1]["mode"] == "full_passage"

        # The invariant also holds when the learner manually chooses word
        # bank with automatic grain: only whole recall lines receive chips.
        manual_bank = build_plan(db, revision, ["word_bank"], None)
        assert [kinds[item["segment_id"]] for item in manual_bank] == ["line", "line"]


def test_juncture_history_is_grandfathered_before_flanks_master(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-juncture-history", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        first = models.Segment(kind="line", ordinal=0, text="line zero")
        juncture = models.Segment(
            kind="juncture",
            ordinal=1,
            text="line one opening",
            metadata_json={"juncture_after": 0},
        )
        second = models.Segment(kind="line", ordinal=1, text="line one")
        revision.segments = [first, juncture, second]
        db.add(passage)
        db.flush()
        db.add(
            models.ReviewState(
                segment_id=juncture.id,
                fsrs_card_json="{}",
                due_at=datetime.now(UTC) + timedelta(days=30),
                mastery_stage="learning",
                clean_count=0,
                attempt_count=1,
                acquisition_succeeded=False,
                learning_step=None,
            )
        )
        db.commit()

        plan = build_smart_plan(db, revision, None)
        # The single sweep deals the seam right before its landing line —
        # sessions never jump backward to a juncture after the frontier work.
        assert [item["segment_id"] for item in plan] == [
            first.id,
            juncture.id,
            second.id,
        ]


def test_due_mastered_lines_and_juncture_are_passage_ordered(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-due-juncture", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        first = models.Segment(kind="line", ordinal=0, text="line zero")
        juncture = models.Segment(
            kind="juncture",
            ordinal=1,
            text="line one opening",
            metadata_json={"juncture_after": 0},
        )
        second = models.Segment(kind="line", ordinal=1, text="line one")
        revision.segments = [first, juncture, second]
        db.add(passage)
        db.flush()
        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="review",
                    clean_count=2,
                    attempt_count=2,
                    acquisition_succeeded=True,
                    learning_step=None,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, None)
        assert plan[0]["mode"] == "forward_chaining"
        assert [item["segment_id"] for item in plan[1:-1]] == [
            first.id,
            juncture.id,
            second.id,
        ]
        assert plan[-1]["mode"] == "full_passage"


def test_new_lines_use_one_acquisition_item_even_with_reference_audio(
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

        # Lines use the composite lesson; the unstarted juncture waits for
        # both flanking lines to be started before it is dealt at all.
        plan = build_smart_plan(db, revision, None)
        assert [item["mode"] for item in plan] == [
            "acquisition",
            "acquisition",
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

        # Reference audio remains available inside the encounter surface; it
        # must not split first exposure into a second graded shadowing item.
        plan = build_smart_plan(db, revision, None)
        kinds = {s.id: s.kind for s in revision.segments}
        assert [(kinds[item["segment_id"]], item["mode"]) for item in plan] == [
            ("line", "acquisition"),
            ("line", "acquisition"),
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


def test_spaced_language_lead_in_keeps_word_spaces(session_factory: object) -> None:
    # Greek/Latin lines are space-delimited: the token-based lead-in must keep
    # the spaces, or the opening smushes into one run ("μῆνινἄειδε").
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="greek-lead-in", name="Ancient Greek")
        passage = models.Passage(title="Iliad", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="μῆνιν ἄειδε θεά"
        )
        line = models.Segment(kind="line", ordinal=0, text="μῆνιν ἄειδε θεά")
        line.children = [
            models.Segment(kind="token", ordinal=0, text="μῆνιν"),
            models.Segment(kind="token", ordinal=1, text="ἄειδε"),
            models.Segment(kind="token", ordinal=2, text="θεά"),
        ]
        revision.segments = [line, *line.children]
        db.add(passage)
        db.commit()

        prompt = prompt_for("cue_recall", line, [line])
        assert prompt["lead_in"] == "μῆνιν ἄειδε"


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

        # A fresh passage introduces exactly the three runway lines.
        plan = build_smart_plan(db, revision, ["line"], minutes=5)
        assert len(plan) == 3

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

        # Fully mastered: the finisher is budgeted first (120s default),
        # leaving 180s for three 60-second typed reviews.
        plan = build_smart_plan(db, revision, ["line"], minutes=5)
        assert plan[-1]["mode"] == "full_passage"
        assert len(plan) == 4
        assert all(item["mode"] != "random_start" for item in plan)


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
        # Mid-ladder lines receive three consecutive guided cards apiece.
        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                    acquisition_succeeded=True,
                    learning_step=0,
                )
            )
        db.commit()

        # No budget: one three-rep block for each runway line.
        standard = build_smart_plan(db, revision, ["line"])
        assert [item["mode"] for item in standard] == ["guided_recall"] * 9

        # Ladder material is EXEMPT from minutes fills: a guided block already
        # masses its three successes, and extra cold-production reps would
        # reintroduce exactly the cards the ladder defers. Any leftover budget
        # therefore buys nothing on a passage that is all mid-ladder.
        plan = build_smart_plan(db, revision, ["line"], minutes=120)
        assert [item["mode"] for item in plan] == ["guided_recall"] * 9


def test_minutes_fill_never_assigns_chaining_to_junctures(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="latin-juncture-fill", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=0, text="line 0"),
            models.Segment(
                kind="juncture",
                ordinal=1,
                text="line 1 opening",
                metadata_json={"juncture_after": 0},
            ),
            models.Segment(kind="line", ordinal=1, text="line 1"),
        ]
        db.add(passage)
        db.commit()
        # Both flanks mastered and due, the juncture mid-learning: the fill
        # rounds must reach the juncture (a fresh passage would gate it out
        # and assert nothing) yet never hand it chaining or word_bank.
        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json="{}",
                    due_at=datetime.now(UTC) - timedelta(minutes=1),
                    mastery_stage="learning" if segment.kind == "juncture" else "review",
                    clean_count=0 if segment.kind == "juncture" else 2,
                    attempt_count=1,
                    # A mid-learning juncture has not yet succeeded acquisition;
                    # learning_step is a line-ladder field and stays None.
                    acquisition_succeeded=segment.kind != "juncture",
                    learning_step=None,
                )
            )
        db.commit()

        plan = build_smart_plan(db, revision, None, minutes=120)
        juncture_id = revision.segments[1].id
        juncture_modes = {
            item["mode"] for item in plan if item["segment_id"] == juncture_id
        }
        assert juncture_modes
        assert juncture_modes.isdisjoint(
            {"forward_chaining", "backward_chaining", "word_bank"}
        )
        assert all(item["mode"] != "random_start" for item in plan)


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
        "guided_recall": "stop",
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
        assert "lines 1-2 in this passage" in instruction, (mode, instruction)
        assert prompt["range_label"] == "lines 1-2 in this passage"
        assert prompt["line_start"] == 1
        assert prompt["line_end"] == 2
        assert prompt["chain_segment_ids"] == [line.id, following.id]


def test_chaining_prefers_source_references_over_local_ordinals() -> None:
    first = models.Segment(
        kind="line", ordinal=0, text="alpha beta", reference_label="Iliad 1.6"
    )
    second = models.Segment(
        kind="line", ordinal=1, text="gamma delta", reference_label="Iliad 1.7"
    )

    prompt = prompt_for("forward_chaining", first, [first, second], line_numbers=[1, 2])

    assert prompt["range_label"] == "Iliad 1.6 through Iliad 1.7"
    assert prompt["instruction"] == (
        "From memory, recite Iliad 1.6 through Iliad 1.7, then check."
    )
    assert prompt["chain_reference_labels"] == ["Iliad 1.6", "Iliad 1.7"]


def test_both_failure_ratings_schedule_as_lapses() -> None:
    # "incorrect" means errors in verbatim recall — a failed card. Scheduling
    # it as FSRS Hard (a pass) would extend the interval on exactly the lines
    # that need reps; only the ladder distinguishes the two failure kinds.
    assert RATING_MAP["revealed"] == Rating.Again
    assert RATING_MAP["incorrect"] == Rating.Again
    assert RATING_MAP["hesitant"] == Rating.Good
    assert RATING_MAP["clean"] == Rating.Easy


def test_two_consecutive_failures_drop_a_ladder_phase(session_factory: object) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="ladder-demote", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text=f"line {index} one two three four")
            for index in range(4)
        ] + [models.Segment(kind="juncture", ordinal=1, text="line 1 …", cue="four")]
        db.add(passage)
        db.commit()
        line, mastered, steady, stalled, seam = revision.segments
        for segment, step in (
            (line, 2),
            (mastered, None),
            (steady, 2),
            (stalled, 0),
            (seam, None),
        ):
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json=Card().to_json(),
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                    acquisition_succeeded=True,
                    learning_step=step,
                    learning_success_count=2,
                )
            )
        session = models.PracticeSession(revision_id=revision.id, plan={})
        db.add(session)
        db.flush()
        item = models.PracticeItem(
            session_id=session.id, position=0, mode="cue_recall", prompt={}
        )
        db.add(item)
        db.flush()
        clock = datetime.now(UTC)

        def grade(segment: models.Segment, rating: str) -> models.ReviewState:
            # Replays what submit_attempt does: the attempt row lands first, so
            # the review reads it as history rather than as its own precedent.
            nonlocal clock
            clock += timedelta(minutes=1)
            attempt = models.Attempt(
                session_id=session.id,
                item_id=item.id,
                segment_id=segment.id,
                mode="cue_recall",
                rating=rating,
                created_at=clock,
            )
            db.add(attempt)
            db.flush()
            state = review_segment(
                db, segment.id, rating, attempt_id=attempt.id, mode="cue_recall"
            )
            db.flush()
            return state

        # Mid-ladder: the second failure widens support by one phase and the
        # phase's success credit restarts. The first failure alone does not.
        assert grade(line, "incorrect").learning_step == 2
        demoted = grade(line, "revealed")
        assert (demoted.learning_step, demoted.learning_success_count) == (1, 0)

        # A mastered line re-enters at the LAST phase — the lightest scaffold,
        # not the whole ladder again.
        grade(mastered, "revealed")
        relapsed = grade(mastered, "incorrect")
        assert relapsed.learning_step == len(learning_scaffold_steps(mastered)) - 1
        assert relapsed.learning_success_count == 0
        assert relapsed.mastery_stage == "learning"

        # Failures split by a success are not consecutive.
        grade(steady, "incorrect")
        grade(steady, "clean")
        assert grade(steady, "revealed").learning_step == 2

        # Step zero already re-engages acquisition support; junctures have no
        # ladder to fall down.
        grade(stalled, "incorrect")
        assert grade(stalled, "revealed").learning_step == 0
        grade(seam, "incorrect")
        assert grade(seam, "revealed").learning_step is None


def test_clean_guided_recall_counts_as_two_phase_successes(
    session_factory: object,
) -> None:
    with session_factory() as db:  # type: ignore[operator]
        language = models.LanguageProfile(slug="ladder-credit", name="Latin")
        passage = models.Passage(title="Aeneid", language_profile=language)
        revision = models.PassageRevision(
            passage=passage, revision_number=1, source_text="..."
        )
        # Four words put the first phase at the plain three-success threshold.
        revision.segments = [
            models.Segment(kind="line", ordinal=index, text="alpha beta gamma delta")
            for index in range(3)
        ]
        db.add(passage)
        db.commit()
        mixed, doubled, overshooting = revision.segments
        assert learning_step_successes_required(mixed, 0) == 3
        for segment in revision.segments:
            db.add(
                models.ReviewState(
                    segment_id=segment.id,
                    fsrs_card_json=Card().to_json(),
                    due_at=datetime.now(UTC),
                    mastery_stage="learning",
                    clean_count=0,
                    attempt_count=1,
                    acquisition_succeeded=True,
                    learning_step=0,
                    learning_success_count=0,
                )
            )
        db.flush()

        def grade(segment: models.Segment, rating: str) -> models.ReviewState:
            state = review_segment(db, segment.id, rating, mode="guided_recall")
            db.flush()
            return state

        # A clean recall banks two of the three, but does not skip the phase.
        partway = grade(mixed, "clean")
        assert (partway.learning_step, partway.learning_success_count) == (0, 2)
        advanced = grade(mixed, "hesitant")
        assert (advanced.learning_step, advanced.learning_success_count) == (1, 0)

        # Two cleans alone finish the phase.
        assert grade(doubled, "clean").learning_step == 0
        assert grade(doubled, "clean").learning_step == 1

        # Landing past the requirement rather than exactly on it still advances.
        grade(overshooting, "hesitant")
        grade(overshooting, "hesitant")
        overshot = grade(overshooting, "clean")
        assert (overshot.learning_step, overshot.learning_success_count) == (1, 0)


def test_chain_failure_falls_on_the_last_line_only() -> None:
    chain = [("first", "clean"), ("middle", "clean"), ("last", "clean")]

    failed = session_service.attribute_chain_failure("forward_chaining", "revealed", chain)
    assert failed == [("first", "hesitant"), ("middle", "hesitant"), ("last", "clean")]
    assert session_service.attribute_chain_failure("full_passage", "incorrect", chain)[-1] == (
        "last",
        "clean",
    )
    # Successes still fan; recital already grades per line from its stumble map.
    assert session_service.attribute_chain_failure("full_passage", "clean", chain) == chain
    assert session_service.attribute_chain_failure("recital", "incorrect", chain) == chain
    single = chain[:1]
    assert session_service.attribute_chain_failure("cue_recall", "incorrect", single) == single


def test_fsrs_parameters_load_from_settings_with_safe_fallback(
    session_factory: object,
) -> None:
    from rhapsode.services.scheduling import _fsrs_parameters, _scheduler

    with session_factory() as db:  # type: ignore[operator]
        # Absent → defaults (None signals the Scheduler to use its own).
        assert _fsrs_parameters(db) is None
        db.add(models.AppSetting(key="fsrs_parameters", value=[0.4] * 21))
        db.commit()
        assert _fsrs_parameters(db) == [0.4] * 21
        assert _scheduler(db) is not None
        # Malformed values must never break grading.
        db.get(models.AppSetting, "fsrs_parameters").value = ["not", "numbers"]
        db.commit()
        assert _fsrs_parameters(db) is None


def test_mastery_stages() -> None:
    state = models.ReviewState(
        segment_id="segment",
        fsrs_card_json="{}",
        due_at=datetime.now(UTC),
        attempt_count=1,
        clean_count=0,
        acquisition_succeeded=True,
    )
    assert mastery_stage(state) == "learning"
    state.clean_count = 2
    assert mastery_stage(state) == "review"
    state.clean_count = 5
    assert mastery_stage(state) == "durable"
    state.acquisition_succeeded = False
    assert mastery_stage(state) == "new"


def test_acquisition_prompt_carries_exact_target_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reverse(items: list[str]) -> None:
        items.reverse()

    monkeypatch.setattr(planning.random, "shuffle", reverse)
    line = models.Segment(
        kind="line",
        ordinal=0,
        text="arma virumque cano",
        cue="arms and the man",
    )

    prompt = prompt_for("acquisition", line, [line], hint="my memory hook")

    assert prompt == {
        "instruction": "Learn this line, then rebuild it from its own words.",
        "target_text": "arma virumque cano",
        "word_bank": ["cano", "virumque", "arma"],
        "hint": "my memory hook",
    }


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
