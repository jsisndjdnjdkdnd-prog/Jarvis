from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.intent import Intent, IntentName

GREETINGS_BY_PERIOD: dict[str, tuple[str, ...]] = {
    "morning": ("Доброго ранку, сер.", "Доброго ранку. Всі системи в нормі."),
    "day": ("Добрий день, сер. До ваших послуг.", "Вітаю, сер. Чим можу допомогти?"),
    "evening": ("Добрий вечір, сер.", "Добрий вечір. Слухаю вас."),
    "night": ("Доброї ночі, сер. Ви знову не спите?", "Слухаю, сер. Пізно вже."),
}
THANKS_REPLIES: tuple[str, ...] = ("Завжди до ваших послуг, сер.", "Радий допомогти.", "Для вас — що завгодно, сер.")


def _period(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "day"
    if 18 <= hour < 23:
        return "evening"
    return "night"


class ConversationSkill:
    name = "conversation"
    intents = frozenset({IntentName.GREETING, IntentName.THANKS, IntentName.CHAT})

    def __init__(
        self,
        clock: Callable[[], datetime] = datetime.now,
        rng: random.Random | None = None,
    ) -> None:
        self._clock = clock
        self._rng = rng or random.Random()

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.GREETING:
            options = GREETINGS_BY_PERIOD[_period(self._clock().hour)]
            return SkillResult(self._rng.choice(options))
        if intent.name is IntentName.THANKS:
            return SkillResult(self._rng.choice(THANKS_REPLIES))
        reply = (intent.reply or "").strip()
        if not reply:
            return SkillResult("Боюся, на це в мене немає відповіді, сер.", success=False, learnable=False)
        return SkillResult(reply, learnable=False)
