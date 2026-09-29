from __future__ import annotations

from jarvis.core.intent import Intent, IntentName, WeatherPeriod
from jarvis.nlu import lexicon_ext as lxe
from jarvis.nlu.geo import CITY_PREPOSITIONS, CityNormalizer
from jarvis.nlu.prepared_text import PreparedText, Rule
from jarvis.nlu.time_parser import NaturalTimeParser

WEATHER_NOISE: frozenset[str] = frozenset(
    {"яка", "який", "яке", "буде", "зараз", "сьогодні", "завтра", "погода", "погоду", "прогноз", "погоди",
     "a", "the", "is", "what", "what's", "какая", "будет", "там", "на", "вулиці"}
)


class InfoRules:
    def __init__(self, time_parser: NaturalTimeParser, cities: CityNormalizer | None = None) -> None:
        self._time_parser = time_parser
        self._cities = cities or CityNormalizer()

    def rules(self) -> tuple[Rule, ...]:
        return (self.alarm, self.calculate, self.weather, self.system_info)

    def alarm(self, prepared: PreparedText) -> Intent | None:
        for prefix in lxe.ALARM_PREFIXES:
            if not prepared.core.startswith(prefix):
                continue
            rest = prepared.core[len(prefix) :].strip()
            extraction = self._time_parser.extract(rest, prefer_afternoon=False)
            if extraction is None:
                return Intent(name=IntentName.REMINDER_ADD, message=lxe.ALARM_MESSAGE)
            return Intent(name=IntentName.REMINDER_ADD, when=extraction.when, message=lxe.ALARM_MESSAGE)
        return None

    def calculate(self, prepared: PreparedText) -> Intent | None:
        starts = any(prepared.core.startswith(prefix + " ") for prefix in lxe.CALCULATE_PREFIXES)
        has_operator = prepared.has_stem(lxe.CALCULATE_OPERATOR_STEMS)
        has_number = prepared.first_number() is not None
        if starts and (has_operator or has_number):
            return Intent(name=IntentName.CALCULATE, query=prepared.core)
        if has_operator and has_number and not prepared.has_stem(lxe.VOLUME_CONTEXT_WORDS):
            return Intent(name=IntentName.CALCULATE, query=prepared.core)
        return None

    def weather(self, prepared: PreparedText) -> Intent | None:
        if not (prepared.has_stem(lxe.WEATHER_STEMS) or prepared.contains(lxe.WEATHER_PHRASES)):
            return None
        return Intent(name=IntentName.WEATHER, target=self._city(prepared), mode=self._period(prepared).value)

    @staticmethod
    def _period(prepared: PreparedText) -> WeatherPeriod:
        if prepared.has_token(lxe.WEATHER_TOMORROW_WORDS):
            return WeatherPeriod.TOMORROW
        if prepared.has_token(lxe.WEATHER_TODAY_WORDS) and "зараз" not in prepared.tokens:
            return WeatherPeriod.TODAY
        return WeatherPeriod.NOW

    def _city(self, prepared: PreparedText) -> str | None:
        tokens = list(prepared.tokens)
        for index, token in enumerate(tokens):
            if token not in CITY_PREPOSITIONS or index + 1 >= len(tokens):
                continue
            words = [word for word in tokens[index + 1 : index + 3] if word not in WEATHER_NOISE]
            if not words or words[0] in WEATHER_NOISE:
                continue
            city = self._cities.normalize(" ".join(words[:2] if self._is_two_word_city(words) else words[:1]))
            if city:
                return city
        return None

    @staticmethod
    def _is_two_word_city(words: list[str]) -> bool:
        return len(words) >= 2 and " ".join(words[:2]) in {"білій церкві", "нью йорку", "івано франківську"}

    def system_info(self, prepared: PreparedText) -> Intent | None:
        for phrases, kind in lxe.SYSTEM_INFO_PHRASES:
            single = [phrase for phrase in phrases if " " not in phrase]
            multi = [phrase for phrase in phrases if " " in phrase]
            if prepared.contains(multi) or (len(prepared.tokens) <= 3 and prepared.has_token(single)):
                return Intent(name=IntentName.SYSTEM_INFO, mode=kind.value)
        return None
