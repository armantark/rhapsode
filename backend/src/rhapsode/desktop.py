"""Desktop-only HTTP concerns for the Tauri sidecar."""

from __future__ import annotations

DEFAULT_DESKTOP_CORS_ORIGINS: tuple[str, ...] = (
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
)
