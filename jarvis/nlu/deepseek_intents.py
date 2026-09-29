from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from jarvis.core.intent import Intent, IntentName
from jarvis.nlu.deepseek_client import DeepSeekClient

INTENT_PURPOSE = "intent"

_INTENT_GUIDE: dict[IntentName, str] = {
    IntentName.OPEN_APP: "launch a program or game; target = program name as user said it",
    IntentName.CLOSE_APP: "close a program; target = program name or null for 'it'",
    IntentName.OPEN_FOLDER: "open a folder; target = folder name or path",
    IntentName.OPEN_URL: "open a website; target = url or domain",
    IntentName.RESCAN_PROGRAMS: "re-index installed programs",
    IntentName.PLAY_MUSIC: "play a specific track/artist on SoundCloud; query = search text",
    IntentName.PLAY_RECOMMENDED: "play something the assistant chooses; query = mood/genre hint or null",
    IntentName.MUSIC_PAUSE: "pause music",
    IntentName.MUSIC_RESUME: "resume music",
    IntentName.MUSIC_NEXT: "next track",
    IntentName.MUSIC_STOP: "stop music",
    IntentName.MUSIC_NOW_PLAYING: "tell what is playing",
    IntentName.MUSIC_LIKE: "remember that user likes current track",
    IntentName.MUSIC_VOLUME_UP: "player louder; amount = percent or null",
    IntentName.MUSIC_VOLUME_DOWN: "player quieter; amount = percent or null",
    IntentName.VOLUME_UP: "system volume up; amount = percent or null",
    IntentName.VOLUME_DOWN: "system volume down; amount = percent or null",
    IntentName.VOLUME_SET: "set system volume; amount = 0..100",
    IntentName.MUTE: "mute system sound",
    IntentName.UNMUTE: "unmute system sound",
    IntentName.TIMER_SET: "start timer; duration_seconds = integer",
    IntentName.TIMER_STATUS: "how much time is left on timers",
    IntentName.TIMER_CANCEL: "cancel timers; mode = 'all' or null",
    IntentName.REMINDER_ADD: "reminder; when = ISO datetime 'YYYY-MM-DDTHH:MM:SS' local time; message = text",
    IntentName.REMINDER_LIST: "list reminders",
    IntentName.REMINDER_CANCEL: "cancel reminder; query = text or mode = 'all'",
    IntentName.SCREENSHOT: "screenshot; mode = 'full' | 'window' | 'region'",
    IntentName.TIME_NOW: "tell current time",
    IntentName.DATE_NOW: "tell current date",
    IntentName.LOCK_PC: "lock computer",
    IntentName.SHUTDOWN_PC: "shut down computer",
    IntentName.RESTART_PC: "restart computer",
    IntentName.GREETING: "greeting",
    IntentName.THANKS: "gratitude",
    IntentName.CHAT: "general question or conversation; reply = short answer in Ukrainian (max 2 sentences)",
    IntentName.UNKNOWN: "cannot be mapped to anything",
}

_ALLOWED_FIELDS = (
    "name, target, query, message, mode, amount, duration_seconds, when, reply, confidence"
)


def build_intent_system_prompt(now: datetime) -> str:
    intents = "\n".join(f"- {name.value}: {description}" for name, description in _INTENT_GUIDE.items())
    return (
        "You are the command parser of a Windows voice assistant called JARVIS. "
        "The user speaks Ukrainian (sometimes Russian or English); text comes from speech "
        "recognition and may contain recognition errors, so infer the most plausible meaning. "
        "Classify the command into exactly one intent and extract its slots.\n"
        f"Current local datetime: {now.isoformat(timespec='minutes')} ({now.strftime('%A')}).\n"
        f"Allowed intents:\n{intents}\n"
        f"Output format: a single JSON object with fields {_ALLOWED_FIELDS}. "
        "Omit or set null the fields that are not relevant. confidence is 0..1. "
        "Never add explanations or markdown, output json only."
    )


class DeepSeekIntentResolver:
    def __init__(self, client: DeepSeekClient, clock: Callable[[], datetime] = datetime.now) -> None:
        self._client = client
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._client.available

    def resolve(self, text: str) -> Intent:
        return self._client.complete_json(
            system_prompt=build_intent_system_prompt(self._clock()),
            user_prompt=f"Command: {text}",
            purpose=INTENT_PURPOSE,
            parse=self._parse,
        )

    @staticmethod
    def _parse(data: dict[str, Any]) -> Intent:
        cleaned = {key: value for key, value in data.items() if value is not None}
        cleaned.pop("actions", None)
        cleaned.pop("binding_id", None)
        return Intent.model_validate(cleaned)
