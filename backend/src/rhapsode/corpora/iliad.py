from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verse:
    number: int
    text: str
    translation: str


BOOK_ONE_11_20 = (
    Verse(
        11,
        "οὕνεκα τὸν Χρύσην ἠτίμασεν ἀρητῆρα",
        "because he dishonored Chryses, the priest,",
    ),
    Verse(
        12,
        "Ἀτρεΐδης: ὃ γὰρ ἦλθε θοὰς ἐπὶ νῆας Ἀχαιῶν",
        "the son of Atreus; for he came to the swift ships of the Achaeans,",
    ),
    Verse(
        13,
        "λυσόμενός τε θύγατρα φέρων τ᾽ ἀπερείσι᾽ ἄποινα,",
        "to free his daughter, bringing a boundless ransom,",
    ),
    Verse(
        14,
        "στέμματ᾽ ἔχων ἐν χερσὶν ἑκηβόλου Ἀπόλλωνος",
        "holding in his hands the wreaths of far-shooting Apollo",
    ),
    Verse(
        15,
        "χρυσέῳ ἀνὰ σκήπτρῳ, καὶ λίσσετο πάντας Ἀχαιούς,",
        "on a golden staff, and he begged all the Achaeans,",
    ),
    Verse(
        16,
        "Ἀτρεΐδα δὲ μάλιστα δύω, κοσμήτορε λαῶν:",
        "but especially the two sons of Atreus, marshals of the people:",
    ),
    Verse(
        17,
        "Ἀτρεΐδαι τε καὶ ἄλλοι ἐϋκνήμιδες Ἀχαιοί,",
        "Sons of Atreus and you other well-greaved Achaeans,",
    ),
    Verse(
        18,
        "ὑμῖν μὲν θεοὶ δοῖεν Ὀλύμπια δώματ᾽ ἔχοντες",
        "may the gods who dwell in Olympian homes grant you",
    ),
    Verse(
        19,
        "ἐκπέρσαι Πριάμοιο πόλιν, εὖ δ᾽ οἴκαδ᾽ ἱκέσθαι:",
        "to sack Priam's city and return safely home;",
    ),
    Verse(
        20,
        "παῖδα δ᾽ ἐμοὶ λύσαιτε φίλην, τὰ δ᾽ ἄποινα δέχεσθαι,",
        "but release my dear child to me, and accept the ransom,",
    ),
)

PASSAGE_TITLE = "Iliad 11-20"
PASSAGE_REFERENCE = "Iliad 1.11–20"
PASSAGE_DESCRIPTION = "Lines 11-20"
COLLECTION_NAME = "Iliad thus far"


def passage_payload(language_profile_id: str) -> dict[str, Any]:
    """Build the same line/token/translation shape used by Iliad 1.8–10."""
    segments: list[dict[str, Any]] = []
    ordinal = 0
    for verse in BOOK_ONE_11_20:
        line_id = f"iliad-1-{verse.number}"
        segments.append(
            {
                "client_id": line_id,
                "kind": "line",
                "ordinal": ordinal,
                "text": verse.text,
                "reference_label": f"Iliad 1.{verse.number}",
                "annotations": [
                    {"layer": "translation", "value": verse.translation},
                ],
            }
        )
        ordinal += 1
        for token in verse.text.split():
            segments.append(
                {
                    "client_id": f"{line_id}-token-{ordinal}",
                    "parent_client_id": line_id,
                    "kind": "token",
                    "ordinal": ordinal,
                    "text": token,
                }
            )
            ordinal += 1
    return {
        "title": PASSAGE_TITLE,
        "language_profile_id": language_profile_id,
        "description": PASSAGE_DESCRIPTION,
        "source_text": "\n".join(verse.text for verse in BOOK_ONE_11_20),
        "reference_label": PASSAGE_REFERENCE,
        "segments": segments,
    }
