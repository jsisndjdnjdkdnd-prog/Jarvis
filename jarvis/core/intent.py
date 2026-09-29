from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IntentName(StrEnum):
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_FOLDER = "open_folder"
    OPEN_URL = "open_url"
    RESCAN_PROGRAMS = "rescan_programs"
    RUN_BINDING = "run_binding"
    LEARN_BINDING = "learn_binding"
    PLAY_MUSIC = "play_music"
    PLAY_RECOMMENDED = "play_recommended"
    MUSIC_PAUSE = "music_pause"
    MUSIC_RESUME = "music_resume"
    MUSIC_NEXT = "music_next"
    MUSIC_STOP = "music_stop"
    MUSIC_NOW_PLAYING = "music_now_playing"
    MUSIC_LIKE = "music_like"
    MUSIC_VOLUME_UP = "music_volume_up"
    MUSIC_VOLUME_DOWN = "music_volume_down"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    VOLUME_SET = "volume_set"
    MUTE = "mute"
    UNMUTE = "unmute"
    TIMER_SET = "timer_set"
    TIMER_STATUS = "timer_status"
    TIMER_CANCEL = "timer_cancel"
    REMINDER_ADD = "reminder_add"
    REMINDER_LIST = "reminder_list"
    REMINDER_CANCEL = "reminder_cancel"
    SCREENSHOT = "screenshot"
    TIME_NOW = "time_now"
    DATE_NOW = "date_now"
    LOCK_PC = "lock_pc"
    SHUTDOWN_PC = "shutdown_pc"
    RESTART_PC = "restart_pc"
    CONFIRM = "confirm"
    DENY = "deny"
    CORRECTION = "correction"
    GREETING = "greeting"
    THANKS = "thanks"
    CHAT = "chat"
    UNKNOWN = "unknown"


class ScreenshotMode(StrEnum):
    FULL = "full"
    WINDOW = "window"
    REGION = "region"


class ActionType(StrEnum):
    OPEN_APP = "open_app"
    LAUNCH = "launch"
    CLOSE_PROCESS = "close_process"
    OPEN_FOLDER = "open_folder"
    SHELL = "shell"
    HOTKEY = "hotkey"
    PLAY_TRACK = "play_track"
    MACRO = "macro"
    INTENT = "intent"


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: ActionType
    target: str = ""
    steps: tuple[Action, ...] = ()
    intent: Intent | None = None
    delay_seconds: float = 0.0

    def describe(self) -> str:
        if self.type is ActionType.MACRO:
            return " → ".join(step.describe() for step in self.steps)
        if self.type is ActionType.INTENT and self.intent is not None:
            return f"intent:{self.intent.name.value}"
        return f"{self.type.value}:{self.target}"


class Intent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: IntentName
    target: str | None = None
    query: str | None = None
    message: str | None = None
    phrase: str | None = None
    mode: str | None = None
    amount: int | None = None
    duration_seconds: int | None = None
    when: datetime | None = None
    binding_id: int | None = None
    actions: tuple[Action, ...] = ()
    reply: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    def with_updates(self, **changes: object) -> Intent:
        return self.model_copy(update=changes)


Action.model_rebuild()
Intent.model_rebuild()


class ResolutionStage(StrEnum):
    EXACT_BINDING = "exact_binding"
    FUZZY_BINDING = "fuzzy_binding"
    RULES = "rules"
    DEEPSEEK_CACHE = "deepseek_cache"
    DEEPSEEK = "deepseek"
    CONFIRMATION = "confirmation"
