from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.core.context import ExchangeRecord
from jarvis.core.intent import (
    Intent,
    IntentName,
    ScreenshotMode,
    SmallTalkTopic,
    SystemInfoKind,
    WeatherPeriod,
    WindowCommand,
    YouTubeCommand,
)
from jarvis.nlu.dialogue import ChatClient, clean_spoken_text

INTENT_PURPOSE = "intent"
DEFAULT_HISTORY_TURNS = 6
HISTORY_TEXT_LIMIT = 200
USES_HISTORY_FIELD = "uses_history"
DISCARDED_FIELDS: tuple[str, ...] = ("actions", "binding_id")
HISTORY_SLOTS: tuple[str, ...] = ("target", "query", "mode", "amount")

NON_RESOLVABLE_INTENTS: frozenset[IntentName] = frozenset(
    {IntentName.RUN_BINDING, IntentName.LEARN_BINDING, IntentName.RUN_PLAN}
)


def enum_choices(values: Iterable[StrEnum]) -> str:
    return " | ".join(f"'{member.value}'" for member in values)


CHAT_GUIDE = (
    "any other question or conversation the assistant answers itself (facts, advice, opinions, chit-chat); "
    "query = the user's words; reply = the spoken answer of J.A.R.V.I.S., Tony Stark's AI butler "
    "(calm, loyal, polite, dry British wit, subtle irony) in natural spoken Ukrainian, at most 3 short sentences, "
    "no markdown, lists or emoji, addressing the user as 'сер' naturally, not in every sentence; "
    "never claim that an action was performed"
)

_INTENT_GUIDE: dict[IntentName, str] = {
    IntentName.OPEN_APP: (
        "launch a program or game; target = program name as the user said it, with obvious recognition errors fixed"
    ),
    IntentName.CLOSE_APP: "close a program; target = program name, or null for 'it' when unknown",
    IntentName.OPEN_FOLDER: "open a folder; target = folder name or path",
    IntentName.OPEN_URL: "open a website; target = url or domain",
    IntentName.OPEN_SETTINGS: (
        "open a Windows settings page; target = page such as bluetooth, wifi, sound, display, network, updates, "
        "apps, privacy, or null for the main settings"
    ),
    IntentName.RESCAN_PROGRAMS: "re-index installed programs",
    IntentName.PLAY_MUSIC: (
        "play a specific track/artist on SoundCloud; query = search text with artist and track names "
        "in their usual spelling (e.g. 'імаджин драгонс' -> 'Imagine Dragons')"
    ),
    IntentName.PLAY_RECOMMENDED: "play something the assistant chooses; query = mood/genre hint or null",
    IntentName.MUSIC_PAUSE: "pause music",
    IntentName.MUSIC_RESUME: "resume music",
    IntentName.MUSIC_NEXT: "next track",
    IntentName.MUSIC_PREVIOUS: "previous track",
    IntentName.MUSIC_STOP: "stop music",
    IntentName.MUSIC_NOW_PLAYING: "tell what is playing",
    IntentName.MUSIC_LIKE: "remember that user likes current track",
    IntentName.MUSIC_VOLUME_UP: "player louder; amount = percent or null",
    IntentName.MUSIC_VOLUME_DOWN: "player quieter; amount = percent or null",
    IntentName.YOUTUBE_PLAY: "find and play a video on YouTube; query = what to find, or null to just open YouTube",
    IntentName.YOUTUBE_CONTROL: (
        f"control the YouTube player; mode = one of {enum_choices(YouTubeCommand)}; "
        "amount = seconds for forward/backward, otherwise null"
    ),
    IntentName.VOLUME_UP: "system volume up; amount = percent or null",
    IntentName.VOLUME_DOWN: "system volume down; amount = percent or null",
    IntentName.VOLUME_SET: "set system volume; amount = 0..100",
    IntentName.VOLUME_GET: "tell the current system volume level",
    IntentName.MUTE: "mute system sound",
    IntentName.UNMUTE: "unmute system sound",
    IntentName.WINDOW_CONTROL: (
        f"window, browser tab or editing shortcut; mode = one of {enum_choices(WindowCommand)}; "
        "amount = number of repetitions or null"
    ),
    IntentName.TYPE_TEXT: "type text with the keyboard into the active window; message = the text to type",
    IntentName.TIMER_SET: "start timer; duration_seconds = integer",
    IntentName.TIMER_STATUS: "how much time is left on timers",
    IntentName.TIMER_CANCEL: "cancel timers; mode = 'all' or null",
    IntentName.REMINDER_ADD: "reminder; when = ISO datetime 'YYYY-MM-DDTHH:MM:SS' local time; message = text",
    IntentName.REMINDER_LIST: "list reminders",
    IntentName.REMINDER_CANCEL: "cancel reminder; query = text or mode = 'all'",
    IntentName.SCREENSHOT: f"screenshot; mode = {enum_choices(ScreenshotMode)}",
    IntentName.TIME_NOW: "tell current time",
    IntentName.DATE_NOW: "tell current date",
    IntentName.WEATHER: (
        f"weather forecast; target = city name or null for the home city; mode = {enum_choices(WeatherPeriod)}"
    ),
    IntentName.CALCULATE: "arithmetic; query = the math expression words exactly as said",
    IntentName.WEB_SEARCH: "search the web in a browser; query = search text",
    IntentName.SYSTEM_INFO: f"computer status; mode = {enum_choices(SystemInfoKind)}",
    IntentName.LOCK_PC: "lock computer",
    IntentName.SLEEP_PC: "put the computer to sleep",
    IntentName.SHUTDOWN_PC: "shut down computer",
    IntentName.RESTART_PC: "restart computer",
    IntentName.EMPTY_RECYCLE_BIN: "empty the recycle bin",
    IntentName.CONFIRM: "the user agrees to the assistant's pending question ('так', 'підтверджую', 'давай')",
    IntentName.DENY: "the user declines the assistant's pending question ('ні', 'скасуй', 'не треба')",
    IntentName.CORRECTION: "the user says the assistant misunderstood the previous command ('я не це мав на увазі')",
    IntentName.LISTEN_MODE: (
        "change listening mode; mode = 'always' (listen without the wake word) or 'wake' (only after the wake word)"
    ),
    IntentName.STOP_SPEAKING: "interrupt the assistant: stop talking right now ('замовкни', 'тихо', 'досить')",
    IntentName.END_CONVERSATION: (
        "the user ends the dialogue ('дякую, все', 'відпочинь', 'поки що все', 'можеш іти')"
    ),
    IntentName.REPEAT: "repeat the assistant's last reply ('повтори', 'що ти сказав?')",
    IntentName.CAPABILITIES: "the user asks what the assistant can do or asks for help",
    IntentName.GREETING: "greeting",
    IntentName.THANKS: "gratitude",
    IntentName.SMALL_TALK: (
        f"light small talk answered in character; mode = one of {enum_choices(SmallTalkTopic)}; "
        "query = the user's words verbatim; reply = null"
    ),
    IntentName.CHAT: CHAT_GUIDE,
    IntentName.UNKNOWN: "cannot be mapped to anything",
}

_ALLOWED_FIELDS = (
    "name, target, query, message, mode, amount, duration_seconds, when, reply, confidence, uses_history"
)


@dataclass(frozen=True)
class ResolvedIntent:
    intent: Intent
    uses_history: bool = False


def resolvable_intents() -> tuple[IntentName, ...]:
    return tuple(_INTENT_GUIDE)


def build_intent_system_prompt(now: datetime) -> str:
    intents = "\n".join(f"- {name.value}: {description}" for name, description in _INTENT_GUIDE.items())
    return (
        "You are the command parser of a Windows voice assistant called JARVIS. "
        "The user speaks Ukrainian (sometimes Russian or English). The text comes from speech recognition and "
        "often contains misheard or merged words, wrong endings, Russian/Ukrainian mixing and phonetically "
        "spelled foreign names (e.g. 'діскорд' = Discord, 'стім' = Steam, 'ютуб' = YouTube), so reconstruct "
        "the most plausible intended command from how it sounds and prefer a concrete command intent when "
        "the words resemble one.\n"
        "Classify the final command into exactly one intent and extract its slots. A recent conversation may be "
        "given: use it only to resolve follow-ups and references such as 'а завтра?', 'а в Львові?', "
        "'закрий його', 'так' or 'ні'.\n"
        f"Current local datetime: {now.isoformat(timespec='minutes')} ({now.strftime('%A')}).\n"
        f"Allowed intents:\n{intents}\n"
        f"Output format: a single JSON object with fields {_ALLOWED_FIELDS}. "
        "Omit or set null the fields that are not relevant. confidence is 0..1. "
        "uses_history = true only if the command cannot be understood without the recent conversation, "
        "otherwise false. Never add explanations or markdown, output json only."
    )


def build_intent_user_prompt(text: str, history_lines: Sequence[str]) -> str:
    command = f"Command: {text}"
    if not history_lines:
        return command
    return "Recent conversation (oldest first):\n" + "\n".join(history_lines) + f"\n\n{command}"


def format_history(records: Sequence[ExchangeRecord], turns: int) -> list[str]:
    if turns <= 0:
        return []
    usable = [record for record in records if record.text.strip()]
    lines: list[str] = []
    for record in usable[-turns:]:
        lines.append(f"User: {_one_line(record.text)}{_intent_note(record.intent)}")
        if record.reply.strip():
            lines.append(f"Jarvis: {_one_line(record.reply)}")
    return lines


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= HISTORY_TEXT_LIMIT:
        return collapsed
    return collapsed[: HISTORY_TEXT_LIMIT - 1].rstrip() + "…"


def _intent_note(intent: Intent | None) -> str:
    if intent is None:
        return ""
    slots = [f"{slot}={getattr(intent, slot)}" for slot in HISTORY_SLOTS if getattr(intent, slot) is not None]
    details = " ".join([intent.name.value, *slots])
    return f"  [{details}]"


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def parse_resolved_intent(data: dict[str, Any]) -> ResolvedIntent:
    cleaned = {key: value for key, value in data.items() if value is not None}
    uses_history = _is_true(cleaned.pop(USES_HISTORY_FIELD, False))
    for field in DISCARDED_FIELDS:
        cleaned.pop(field, None)
    reply = cleaned.get("reply")
    if isinstance(reply, str):
        spoken = clean_spoken_text(reply)
        if spoken:
            cleaned["reply"] = spoken
        else:
            cleaned.pop("reply")
    return ResolvedIntent(Intent.model_validate(cleaned), uses_history)


class DeepSeekIntentResolver:
    def __init__(
        self,
        client: ChatClient,
        clock: Callable[[], datetime] = datetime.now,
        history: Callable[[], Sequence[ExchangeRecord]] | None = None,
        history_turns: int = DEFAULT_HISTORY_TURNS,
    ) -> None:
        self._client = client
        self._clock = clock
        self._history = history
        self._history_turns = history_turns

    @property
    def available(self) -> bool:
        return self._client.available

    def resolve(self, text: str) -> Intent:
        return self.resolve_detailed(text).intent

    def resolve_detailed(self, text: str) -> ResolvedIntent:
        lines = self.history_lines()
        resolved = self._client.complete_json(
            system_prompt=build_intent_system_prompt(self._clock()),
            user_prompt=build_intent_user_prompt(text, lines),
            purpose=INTENT_PURPOSE,
            parse=parse_resolved_intent,
        )
        if lines:
            return resolved
        return ResolvedIntent(resolved.intent, uses_history=False)

    def history_lines(self) -> list[str]:
        if self._history is None:
            return []
        return format_history(self._history(), self._history_turns)
