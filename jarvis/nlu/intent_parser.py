from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from jarvis.core.intent import Action, Intent, IntentName, ScreenshotMode
from jarvis.nlu import lexicon as lx
from jarvis.nlu.durations import DurationParser
from jarvis.nlu.intent_actions import IntentActionMapper
from jarvis.nlu.numbers import NumberWordsConverter
from jarvis.nlu.prepared_text import PreparedText, Rule
from jarvis.nlu.rules_compound import CompoundRule
from jarvis.nlu.rules_control import ControlRules
from jarvis.nlu.rules_dialogue import DialogueRules
from jarvis.nlu.rules_info import InfoRules
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.time_parser import NaturalTimeParser

ALL_WORDS: frozenset[str] = frozenset({"всі", "все", "усі", "all", "всё"})
SELF_WORDS: frozenset[str] = frozenset({"мені", "мне", "me"})
_JOINER_PATTERN = re.compile(
    "|".join(re.escape(joiner.strip()) for joiner in lx.ACTION_JOINERS if joiner.strip() != ",")
)


class ProgramProbe(Protocol):
    def is_known_program(self, name: str) -> bool: ...


class NoProgramProbe:
    def is_known_program(self, name: str) -> bool:
        return False


class IntentParser:
    def __init__(
        self,
        time_parser: NaturalTimeParser,
        program_probe: ProgramProbe | None = None,
        durations: DurationParser | None = None,
        numbers: NumberWordsConverter | None = None,
        mapper: IntentActionMapper | None = None,
    ) -> None:
        self._time_parser = time_parser
        self._programs = program_probe or NoProgramProbe()
        self._numbers = numbers or NumberWordsConverter()
        self._durations = durations or DurationParser(self._numbers)
        self._mapper = mapper or IntentActionMapper()
        dialogue = DialogueRules()
        info = InfoRules(time_parser)
        control = ControlRules(self._durations)
        compound = CompoundRule(self.parse, self._mapper)
        self._rules: tuple[Rule, ...] = (
            self._confirmation,
            compound.compound,
            self._correction,
            dialogue.stop_speaking,
            dialogue.end_conversation,
            dialogue.listen_mode,
            dialogue.capabilities,
            dialogue.repeat,
            control.type_text,
            dialogue.small_talk,
            self._small_talk,
            self._learn_binding,
            self._music_like,
            info.alarm,
            self._reminders,
            self._timers,
            info.calculate,
            info.weather,
            info.system_info,
            self._screenshot,
            self._clock,
            control.power_extras,
            self._power,
            control.volume_extras,
            self._volume,
            control.youtube_control,
            control.youtube_play,
            control.web_search,
            control.open_settings,
            control.window_control,
            control.previous_track,
            self._music_controls,
            self._rescan,
            self._open_folder,
            self._open_site,
            self._play,
            self._open_app,
            self._close_app,
        )

    def parse(self, text: str) -> Intent | None:
        prepared = self._prepare(text)
        if not prepared.raw:
            return None
        for rule in self._rules:
            intent = rule(prepared)
            if intent is not None:
                return intent
        return None

    def _prepare(self, text: str) -> PreparedText:
        raw = self._numbers.convert(TextNormalizer.basic(text))
        tokens = list(raw.split())
        while len(tokens) > 1 and tokens[0] in lx.LEADING_FILLERS:
            tokens.pop(0)
        return PreparedText(raw=raw, core=" ".join(tokens), tokens=tuple(tokens))

    def _confirmation(self, prepared: PreparedText) -> Intent | None:
        if prepared.raw in lx.CONFIRM_PHRASES:
            return Intent(name=IntentName.CONFIRM)
        if prepared.raw in lx.DENY_PHRASES:
            return Intent(name=IntentName.DENY)
        return None

    def _correction(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lx.CORRECTION_PHRASES):
            return Intent(name=IntentName.CORRECTION)
        return None

    def _small_talk(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lx.GREETING_PHRASES):
            return Intent(name=IntentName.GREETING)
        if prepared.equals(lx.THANKS_PHRASES):
            return Intent(name=IntentName.THANKS)
        return None

    def _learn_binding(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.LEARN_VERBS:
            return None
        body = self._after_trigger(" ".join(prepared.tail))
        if body is None:
            return None
        phrase, actions_text = self._split_phrase_and_actions(body)
        if not phrase:
            return None
        actions = self._parse_actions(actions_text)
        return Intent(name=IntentName.LEARN_BINDING, phrase=phrase, actions=actions)

    @staticmethod
    def _after_trigger(text: str) -> str | None:
        cleaned = text.removeprefix("що ").strip()
        for trigger in lx.LEARN_TRIGGERS:
            if cleaned.startswith(trigger):
                return cleaned[len(trigger) :].strip()
        return None

    @staticmethod
    def _split_phrase_and_actions(body: str) -> tuple[str, str]:
        padded = f" {body} "
        for separator in lx.LEARN_SEPARATORS:
            if separator in padded:
                phrase, actions = padded.split(separator, 1)
                return phrase.strip(), actions.strip()
        tokens = body.split()
        for index, token in enumerate(tokens):
            if index > 0 and token in lx.ACTION_VERBS:
                return " ".join(tokens[:index]), " ".join(tokens[index:])
        return body.strip(), ""

    def _parse_actions(self, text: str) -> tuple[Action, ...]:
        actions: list[Action] = []
        last_verb: str | None = None
        for part in self._split_actions(text):
            tokens = part.split()
            if tokens[0] in lx.ACTION_VERBS:
                last_verb = tokens[0]
                command = part
            elif last_verb is not None:
                command = f"{last_verb} {part}"
            else:
                continue
            intent = self.parse(command)
            if intent is None or intent.name is IntentName.LEARN_BINDING:
                continue
            actions.append(self._mapper.to_action(intent))
        return tuple(actions)

    @staticmethod
    def _split_actions(text: str) -> list[str]:
        normalized = text.replace(",", " , ")
        pieces = re.split(rf"\s+(?:{_JOINER_PATTERN.pattern})\s+|\s+,\s+", f" {normalized} ")
        return [piece.strip() for piece in pieces if piece.strip() and piece.strip() != ","]

    def _music_like(self, prepared: PreparedText) -> Intent | None:
        if len(prepared.tokens) > 7:
            return None
        if prepared.equals(lx.LIKE_PHRASES) or prepared.contains(
            phrase for phrase in lx.LIKE_PHRASES if " " in phrase
        ):
            return Intent(name=IntentName.MUSIC_LIKE)
        return None

    def _reminders(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lx.REMINDER_LIST_PHRASES):
            return Intent(name=IntentName.REMINDER_LIST)
        if prepared.head in lx.CANCEL_VERBS and prepared.has_stem(("нагадуван", "напоминан", "reminder")):
            return self._reminder_cancel(prepared)
        if prepared.head in lx.REMINDER_VERBS:
            return self._reminder_add(prepared)
        return None

    @staticmethod
    def _reminder_cancel(prepared: PreparedText) -> Intent:
        rest = [
            token
            for token in prepared.tail
            if not token.startswith(("нагадуван", "напоминан", "reminder")) and token not in {"про", "о", "about"}
        ]
        if not rest or rest[0] in ALL_WORDS:
            return Intent(name=IntentName.REMINDER_CANCEL, mode="all")
        return Intent(name=IntentName.REMINDER_CANCEL, query=" ".join(rest))

    def _reminder_add(self, prepared: PreparedText) -> Intent:
        rest = list(prepared.tail)
        while rest and rest[0] in SELF_WORDS:
            rest.pop(0)
        text = " ".join(rest)
        extraction = self._time_parser.extract(text)
        if extraction is None:
            return Intent(name=IntentName.REMINDER_ADD, message=self._clean_message(text) or None)
        message = self._clean_message(extraction.remainder)
        return Intent(name=IntentName.REMINDER_ADD, when=extraction.when, message=message or None)

    @staticmethod
    def _clean_message(text: str) -> str:
        tokens = text.split()
        while tokens and (tokens[0] in lx.REMINDER_MESSAGE_PREFIXES or tokens[0] in SELF_WORDS):
            tokens.pop(0)
        return " ".join(tokens)

    def _timers(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lx.TIMER_STATUS_PHRASES):
            return Intent(name=IntentName.TIMER_STATUS)
        if not prepared.has_stem(lx.TIMER_WORDS):
            return None
        if prepared.head in lx.CANCEL_VERBS or prepared.head in lx.OFF_VERBS:
            mode = "all" if any(token in ALL_WORDS for token in prepared.tokens) else None
            return Intent(name=IntentName.TIMER_CANCEL, mode=mode)
        found = self._durations.find(prepared.tokens)
        if found is None:
            return Intent(name=IntentName.TIMER_SET)
        seconds, _, _ = found
        return Intent(name=IntentName.TIMER_SET, duration_seconds=seconds)

    def _screenshot(self, prepared: PreparedText) -> Intent | None:
        if not (prepared.has_stem(("скрін", "скрин", "screenshot")) or prepared.contains(("знімок екрану", "знімок екрана", "снимок экрана"))):
            return None
        if prepared.has_stem(lx.SCREENSHOT_REGION_STEMS):
            return Intent(name=IntentName.SCREENSHOT, mode=ScreenshotMode.REGION.value)
        if prepared.has_stem(lx.SCREENSHOT_WINDOW_STEMS):
            return Intent(name=IntentName.SCREENSHOT, mode=ScreenshotMode.WINDOW.value)
        return Intent(name=IntentName.SCREENSHOT, mode=ScreenshotMode.FULL.value)

    def _clock(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lx.TIME_PHRASES):
            return Intent(name=IntentName.TIME_NOW)
        if prepared.contains(lx.DATE_PHRASES):
            return Intent(name=IntentName.DATE_NOW)
        return None

    def _power(self, prepared: PreparedText) -> Intent | None:
        mentions_pc = any(token in lx.PC_WORDS for token in prepared.tokens)
        if prepared.head in lx.LOCK_WORDS:
            return Intent(name=IntentName.LOCK_PC)
        if prepared.head in lx.RESTART_WORDS and (mentions_pc or len(prepared.tokens) == 1):
            return Intent(name=IntentName.RESTART_PC)
        if prepared.head in lx.OFF_VERBS and mentions_pc:
            return Intent(name=IntentName.SHUTDOWN_PC)
        if prepared.contains(lx.SHUTDOWN_PHRASES):
            return Intent(name=IntentName.SHUTDOWN_PC)
        return None

    def _volume(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lx.MUTE_PHRASES):
            return Intent(name=IntentName.MUTE)
        if prepared.contains(lx.UNMUTE_PHRASES):
            return Intent(name=IntentName.UNMUTE)
        amount = prepared.first_number()
        about_music = prepared.has_stem(lx.MUSIC_STEMS)
        if prepared.contains(lx.VOLUME_UP_PHRASES):
            name = IntentName.MUSIC_VOLUME_UP if about_music else IntentName.VOLUME_UP
            return Intent(name=name, amount=amount)
        if prepared.contains(lx.VOLUME_DOWN_PHRASES):
            name = IntentName.MUSIC_VOLUME_DOWN if about_music else IntentName.VOLUME_DOWN
            return Intent(name=name, amount=amount)
        if amount is not None and prepared.contains(lx.VOLUME_SET_WORDS):
            return Intent(name=IntentName.VOLUME_SET, amount=min(amount, 100))
        return None

    def _music_controls(self, prepared: PreparedText) -> Intent | None:
        checks: tuple[tuple[tuple[str, ...], IntentName], ...] = (
            (lx.NOW_PLAYING_PHRASES, IntentName.MUSIC_NOW_PLAYING),
            (lx.STOP_MUSIC_PHRASES, IntentName.MUSIC_STOP),
            (lx.PAUSE_PHRASES, IntentName.MUSIC_PAUSE),
            (lx.RESUME_PHRASES, IntentName.MUSIC_RESUME),
            (lx.NEXT_PHRASES, IntentName.MUSIC_NEXT),
        )
        for phrases, name in checks:
            if self._matches_control(prepared, phrases):
                return Intent(name=name)
        return None

    @staticmethod
    def _matches_control(prepared: PreparedText, phrases: tuple[str, ...]) -> bool:
        if prepared.equals(phrases):
            return True
        return prepared.contains(phrase for phrase in phrases if " " in phrase)

    def _rescan(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lx.RESCAN_PHRASES):
            return Intent(name=IntentName.RESCAN_PROGRAMS)
        return None

    def _open_folder(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.OPEN_VERBS or len(prepared.tokens) < 3:
            return None
        if prepared.tokens[1] not in lx.FOLDER_WORDS:
            return None
        return Intent(name=IntentName.OPEN_FOLDER, target=" ".join(prepared.tokens[2:]))

    def _open_site(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.OPEN_VERBS or len(prepared.tokens) < 3:
            return None
        if prepared.tokens[1] not in lx.SITE_WORDS:
            return None
        return Intent(name=IntentName.OPEN_URL, target=" ".join(prepared.tokens[2:]))

    def _play(self, prepared: PreparedText) -> Intent | None:
        verb = prepared.head
        if verb not in lx.PLAY_VERBS and verb not in lx.TOGGLE_ON_VERBS:
            return None
        rest = self._strip_object_fillers(prepared.tail)
        if verb == "turn" and rest and rest[0] == "on":
            rest = rest[1:]
        mentions_music = any(token in lx.MUSIC_WORDS for token in rest)
        query = " ".join(
            token for token in rest if token not in lx.MUSIC_WORDS and token not in lx.MUSIC_CONNECTORS
        )
        if self._is_recommendation(query):
            return Intent(name=IntentName.PLAY_RECOMMENDED, query=" ".join(rest) or None)
        if verb in lx.TOGGLE_ON_VERBS and not mentions_music and self._programs.is_known_program(query):
            return Intent(name=IntentName.OPEN_APP, target=query)
        return Intent(name=IntentName.PLAY_MUSIC, query=query)

    @staticmethod
    def _is_recommendation(query: str) -> bool:
        if not query:
            return True
        return any(query == phrase or query.startswith(phrase + " ") for phrase in lx.RECOMMEND_PHRASES)

    def _open_app(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.OPEN_VERBS:
            return None
        rest = self._strip_object_fillers(prepared.tail)
        if not rest:
            return None
        return Intent(name=IntentName.OPEN_APP, target=" ".join(rest))

    def _close_app(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.CLOSE_VERBS and prepared.head not in lx.OFF_VERBS:
            return None
        rest = self._strip_object_fillers(prepared.tail)
        if not rest or all(token in lx.PRONOUNS for token in rest):
            return Intent(name=IntentName.CLOSE_APP)
        return Intent(name=IntentName.CLOSE_APP, target=" ".join(rest))

    @staticmethod
    def _strip_object_fillers(tokens: Iterable[str]) -> list[str]:
        remaining = list(tokens)
        while remaining and remaining[0] in lx.OBJECT_FILLERS:
            remaining.pop(0)
        return remaining
