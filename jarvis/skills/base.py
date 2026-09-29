from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import SkillError, SkillNotFoundError
from jarvis.core.intent import Intent, IntentName

logger = logging.getLogger(__name__)


@runtime_checkable
class Skill(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def intents(self) -> frozenset[IntentName]: ...

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult: ...


class SkillRegistry:
    def __init__(self) -> None:
        self._by_intent: dict[IntentName, Skill] = {}
        self._skills: list[Skill] = []

    def register(self, skill: Skill) -> None:
        for intent_name in skill.intents:
            previous = self._by_intent.get(intent_name)
            if previous is not None:
                logger.warning(
                    "Інтент %s перевизначено: %s → %s", intent_name.value, previous.name, skill.name
                )
            self._by_intent[intent_name] = skill
        self._skills.append(skill)
        logger.debug("Зареєстровано навичку %s", skill.name)

    def register_all(self, skills: Iterable[Skill]) -> None:
        for skill in skills:
            self.register(skill)

    def resolve(self, intent_name: IntentName) -> Skill:
        skill = self._by_intent.get(intent_name)
        if skill is None:
            raise SkillNotFoundError(f"Немає навички для інтенту {intent_name.value}")
        return skill

    @property
    def skills(self) -> tuple[Skill, ...]:
        return tuple(self._skills)


class SkillDispatcher:
    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def dispatch(self, intent: Intent, context: DialogContext) -> SkillResult:
        try:
            skill = self._registry.resolve(intent.name)
        except SkillNotFoundError:
            logger.warning("Інтент %s не підтримується", intent.name.value)
            return SkillResult("Цього я поки не вмію, сер.", success=False)
        try:
            return skill.handle(intent, context)
        except SkillError as error:
            logger.warning("Навичка %s: %s", skill.name, error)
            return SkillResult(self._describe(error), success=False)

    @staticmethod
    def _describe(error: SkillError) -> str:
        message = str(error).strip()
        return message if message else "Не вдалося виконати, сер."
