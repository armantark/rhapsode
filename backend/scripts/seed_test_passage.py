"""Seed an isolated test database with a practiceable passage.

Why this exists: agent/manual testing must never touch the developer's real
data (``data/rhapsode.db`` on port 8000). ``seed_defaults`` only installs
languages and plugins, not any passage, so a fresh test DB has nothing to
drill. This script migrates + seeds whatever database the RHAPSODE_* env vars
point at and idempotently creates one short Greek passage (with auto-generated
junctures) so every practice mode has material to exercise.

Run it through the env-scoped launcher (scripts/test-env.sh seed) so it lands
in data-test, not your live database.
"""

from __future__ import annotations

from sqlalchemy import select

from rhapsode import migrations, models, schemas
from rhapsode.database import SessionLocal
from rhapsode.seed import seed_defaults
from rhapsode.services import passages

TEST_PASSAGE_TITLE = "Sandbox: Iliad 1.1-1.5 (test)"

# Iliad 1.1-1.5. Fixed text so junctures (line N tail -> line N+1 head) are
# deterministic across reseeds; the exact accentuation is irrelevant for a
# throwaway sandbox.
SOURCE_LINES: list[str] = [
    "Μῆνιν ἄειδε, θεά, Πηληϊάδεω Ἀχιλῆος",
    "οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε,",
    "πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν",
    "ἡρώων, αὐτοὺς δὲ ἑλώρια τεῦχε κύνεσσιν",
    "οἰωνοῖσί τε πᾶσι, Διὸς δ᾽ ἐτελείετο βουλή,",
]


def seed_test_passage() -> str:
    migrations.main()
    with SessionLocal() as db:
        seed_defaults(db)
        existing = db.scalar(
            select(models.Passage).where(models.Passage.title == TEST_PASSAGE_TITLE)
        )
        if existing is not None:
            return existing.id

        language = db.scalar(
            select(models.LanguageProfile).where(
                models.LanguageProfile.slug == "ancient-greek"
            )
        )
        if language is None:  # seed_defaults guarantees this; guard for type safety
            raise RuntimeError("ancient-greek language profile missing after seeding")

        passage = models.Passage(title=TEST_PASSAGE_TITLE, language_profile=language)
        db.add(passage)
        db.flush()

        revision_input = schemas.RevisionInput(
            source_text="\n".join(SOURCE_LINES),
            segments=[
                schemas.SegmentInput(kind="line", ordinal=index, text=text)
                for index, text in enumerate(SOURCE_LINES)
            ],
        )
        passages.create_revision(db, passage, revision_input)
        return passage.id


if __name__ == "__main__":
    passage_id = seed_test_passage()
    print(f"test passage ready: {passage_id} ({TEST_PASSAGE_TITLE})")
