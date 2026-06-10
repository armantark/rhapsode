from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rhapsode import models

BUILTIN_LANGUAGES: list[dict[str, Any]] = [
    {
        "slug": "ancient-greek",
        "name": "Ancient Greek",
        "direction": "ltr",
        "fonts": ["Noto Serif", "GFS Didot"],
        "annotation_schemas": [
            {"layer": "translation", "label": "Translation"},
            {"layer": "gloss", "label": "Gloss"},
            {"layer": "grammar", "label": "Grammar"},
            {"layer": "meter", "label": "Meter"},
        ],
        "segmentation_defaults": {"line_breaks": "line", "whitespace": "token"},
        "display_options": {"polytonic": True},
    },
    {
        "slug": "classical-armenian",
        "name": "Classical Armenian",
        "direction": "ltr",
        "fonts": ["Noto Serif Armenian", "Sylfaen"],
        "annotation_schemas": [
            {"layer": "translation", "label": "Translation"},
            {"layer": "gloss", "label": "Gloss"},
            {"layer": "grammar", "label": "Grammar"},
        ],
        "segmentation_defaults": {"line_breaks": "line", "whitespace": "token"},
        "display_options": {},
    },
    {
        "slug": "latin",
        "name": "Latin",
        "direction": "ltr",
        "fonts": ["EB Garamond", "Noto Serif"],
        "annotation_schemas": [
            {"layer": "translation", "label": "Translation"},
            {"layer": "grammar", "label": "Grammar"},
            {"layer": "meter", "label": "Meter"},
        ],
        "segmentation_defaults": {"line_breaks": "line", "whitespace": "token"},
        "display_options": {},
    },
    {
        "slug": "japanese",
        "name": "Japanese",
        "direction": "ltr",
        "fonts": ["Noto Serif JP", "Yu Mincho"],
        "annotation_schemas": [
            {"layer": "reading", "label": "Reading", "render": "ruby"},
            {"layer": "translation", "label": "Translation"},
            {"layer": "gloss", "label": "Gloss"},
        ],
        "segmentation_defaults": {"line_breaks": "line", "manual_tokens": True},
        "display_options": {"supports_vertical": True, "supports_ruby": True},
    },
]

BUILTIN_PLUGINS: list[dict[str, Any]] = [
    {
        "plugin_id": "builtin.practice",
        "kind": "practice_mode",
        "name": "Built-in oral practice modes",
        "version": "1.0.0",
        "config": {
            "modes": [
                "shadowing",
                "progressive_fading",
                "forward_chaining",
                "backward_chaining",
                "cue_recall",
                "random_start",
                "weak_link",
                "full_passage",
            ]
        },
    },
    {
        "plugin_id": "builtin.speech-scoring",
        "kind": "speech_scoring",
        "name": "Speech scoring extension point",
        "version": "1.0.0",
        "enabled": False,
        "config": {"provider": None},
    },
]


def seed_defaults(db: Session) -> None:
    for definition in BUILTIN_LANGUAGES:
        if (
            db.scalar(
                select(models.LanguageProfile).where(
                    models.LanguageProfile.slug == definition["slug"]
                )
            )
            is None
        ):
            db.add(models.LanguageProfile(**definition))
    for definition in BUILTIN_PLUGINS:
        if (
            db.scalar(
                select(models.PluginManifest).where(
                    models.PluginManifest.plugin_id == definition["plugin_id"]
                )
            )
            is None
        ):
            db.add(models.PluginManifest(**definition))
    db.commit()
