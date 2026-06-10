from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, Protocol


class LanguagePlugin(Protocol):
    plugin_id: str

    def segment(self, source_text: str, config: dict[str, Any]) -> list[dict[str, Any]]: ...

    def normalize(self, source_text: str, config: dict[str, Any]) -> str: ...

    def validate(self, source_text: str, config: dict[str, Any]) -> list[str]: ...


class SpeechScoringProvider(Protocol):
    plugin_id: str

    def score(
        self, audio_path: str, expected_text: str, config: dict[str, Any]
    ) -> dict[str, Any]: ...


LanguagePluginFactory = Callable[[], LanguagePlugin]
SpeechProviderFactory = Callable[[], SpeechScoringProvider]

language_plugins: dict[str, LanguagePluginFactory] = {}
speech_providers: dict[str, SpeechProviderFactory] = {}


def register_language_plugin(plugin_id: str, factory: LanguagePluginFactory) -> None:
    language_plugins[plugin_id] = factory


def register_speech_provider(plugin_id: str, factory: SpeechProviderFactory) -> None:
    speech_providers[plugin_id] = factory


def discover_entry_point_plugins() -> None:
    for entry_point in entry_points(group="rhapsode.language_plugins"):
        register_language_plugin(entry_point.name, entry_point.load())
    for entry_point in entry_points(group="rhapsode.speech_providers"):
        register_speech_provider(entry_point.name, entry_point.load())
