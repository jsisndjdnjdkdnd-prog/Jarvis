from __future__ import annotations

import logging
import os
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.core.errors import ConfigError
from jarvis.core.paths import AppPaths

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"

logger = logging.getLogger(__name__)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppSection(_Section):
    name: str = "J.A.R.V.I.S."
    log_level: str = "INFO"
    log_file: Path = Path("data/logs/jarvis.log")
    data_dir: Path = Path("data")


class StorageSection(_Section):
    database: Path = Path("data/jarvis.db")


class WakeSection(_Section):
    enabled: bool = True
    words: list[str] = Field(default_factory=lambda: ["джарвіс", "джарвис", "jarvis"])
    threshold: float = 80.0
    min_command_tail_seconds: float = 0.4


class SpeechSection(_Section):
    sample_rate: int = 16000
    block_size: int = 4000
    input_device: int | str | None = None
    primary_language: str = "uk"
    models: dict[str, Path] = Field(
        default_factory=lambda: {"uk": Path("models/vosk-model-uk-v3")}
    )
    secondary_languages: list[str] = Field(default_factory=list)
    secondary_min_confidence: float = 0.6
    wake: WakeSection = Field(default_factory=WakeSection)
    command_timeout_seconds: float = 6.0
    max_command_seconds: float = 12.0
    min_word_confidence: float = 0.55
    grammar_enabled: bool = True


class TtsSection(_Section):
    enabled: bool = True
    voice: str = "uk-UA-OstapNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    cache_dir: Path = Path("data/tts_cache")
    offline_fallback: bool = True


class NluSection(_Section):
    binding_threshold: float = 80.0
    program_threshold: float = 78.0
    alias_threshold: float = 78.0
    alias_prefilter: float = 55.0
    alias_weight: float = 0.6
    acoustic_weight: float = 0.4
    vocabulary_decision_threshold: float = 0.62
    alias_max_window: int = 4
    alias_reward: float = 0.05
    alias_penalty: float = 0.25
    alias_min_weight: float = 0.3


class DeepSeekSection(_Section):
    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_seconds: float = 15.0
    max_tokens: int = 400
    max_retries: int = 2
    temperature: float = 0.0


class MusicBackend(StrEnum):
    VLC = "vlc"
    BROWSER = "browser"


class MusicSection(_Section):
    backend: MusicBackend = MusicBackend.VLC
    soundcloud_client_id: str | None = None
    search_results: int = 5
    recent_history_size: int = 20
    volume_step: int = 10
    initial_volume: int = 70


class ScreenshotsSection(_Section):
    directory: Path = Path("~/Pictures/Jarvis")
    copy_to_clipboard: bool = True
    region_timeout_seconds: float = 30.0


class SystemSection(_Section):
    volume_step: int = 10
    shutdown_delay_seconds: int = 5


class RemindersSection(_Section):
    check_interval_seconds: float = 15.0
    default_hour: int = 9


class ProgramsSection(_Section):
    reindex_on_start: bool = True
    reindex_max_age_hours: float = 24.0
    scan_depth: int = 3
    close_timeout_seconds: float = 3.0


class TrainingSection(_Section):
    min_samples: int = 3
    recommended_samples: int = 5
    max_sample_seconds: float = 3.0
    end_silence_seconds: float = 0.6
    voice_dir: Path = Path("data/voice")
    mfcc_features: int = 13
    alternatives: int = 5
    threshold_std_factor: float = 2.0
    threshold_min_margin: float = 1.15


class UiSection(_Section):
    window_width: int = 1320
    window_height: int = 840
    hud_enabled: bool = True
    hud_size: int = 210
    push_to_talk_hotkey: str = "ctrl+alt+j"
    start_minimized: bool = False
    tray_enabled: bool = True
    devtools: bool = False


class AppConfig(_Section):
    app: AppSection = Field(default_factory=AppSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    speech: SpeechSection = Field(default_factory=SpeechSection)
    tts: TtsSection = Field(default_factory=TtsSection)
    nlu: NluSection = Field(default_factory=NluSection)
    deepseek: DeepSeekSection = Field(default_factory=DeepSeekSection)
    music: MusicSection = Field(default_factory=MusicSection)
    screenshots: ScreenshotsSection = Field(default_factory=ScreenshotsSection)
    system: SystemSection = Field(default_factory=SystemSection)
    reminders: RemindersSection = Field(default_factory=RemindersSection)
    programs: ProgramsSection = Field(default_factory=ProgramsSection)
    training: TrainingSection = Field(default_factory=TrainingSection)
    ui: UiSection = Field(default_factory=UiSection)


class ConfigRepository:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    @property
    def path(self) -> Path:
        return self._paths.user_config_file

    def load(self) -> AppConfig:
        self._ensure_user_config()
        return self._parse(self._read_raw())

    def update(self, changes: dict[str, Any]) -> AppConfig:
        raw = self._read_raw()
        merged = _deep_merge(raw, changes)
        config = self._parse(merged)
        self._write_raw(merged)
        return config

    def _ensure_user_config(self) -> None:
        if self.path.exists():
            return
        if not self._paths.default_config_file.exists():
            return
        shutil.copyfile(self._paths.default_config_file, self.path)
        logger.info("Створено конфігурацію користувача: %s", self.path)

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ConfigError(f"Не вдалося прочитати {self.path}: {error}") from error
        return loaded if isinstance(loaded, dict) else {}

    def _write_raw(self, raw: dict[str, Any]) -> None:
        try:
            self.path.write_text(
                yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        except OSError as error:
            raise ConfigError(f"Не вдалося записати {self.path}: {error}") from error

    @staticmethod
    def _parse(raw: dict[str, Any]) -> AppConfig:
        try:
            return AppConfig.model_validate(raw)
        except ValidationError as error:
            raise ConfigError(f"Некоректний config.yaml: {error}") from error


def read_deepseek_api_key() -> str | None:
    value = os.environ.get(DEEPSEEK_API_KEY_ENV, "").strip()
    return value or None


def _deep_merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in changes.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
            continue
        merged[key] = value
    return merged
