from __future__ import annotations

import logging

from jarvis.core.context import DialogContext, PendingConfirmation, SkillResult
from jarvis.core.errors import StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import BindingsChanged
from jarvis.core.intent import Action, ActionType, Intent, IntentName
from jarvis.core.models import Binding, BindingSource
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.skills.actions import ActionExecutor
from jarvis.storage.repositories.bindings import BindingRepository

logger = logging.getLogger(__name__)

ACTION_WORDS: dict[ActionType, str] = {
    ActionType.OPEN_APP: "відкрити",
    ActionType.LAUNCH: "запустити",
    ActionType.CLOSE_PROCESS: "закрити",
    ActionType.OPEN_FOLDER: "відкрити папку",
    ActionType.SHELL: "виконати",
    ActionType.HOTKEY: "натиснути",
    ActionType.PLAY_TRACK: "увімкнути",
}


def describe_action(action: Action) -> str:
    if action.type is ActionType.MACRO:
        return ", ".join(describe_action(step) for step in action.steps)
    if action.type is ActionType.INTENT and action.intent is not None:
        return action.intent.name.value.replace("_", " ")
    return f"{ACTION_WORDS.get(action.type, action.type.value)} {action.target}".strip()


class BindingsSkill:
    name = "bindings"
    intents = frozenset({IntentName.RUN_BINDING, IntentName.LEARN_BINDING})

    def __init__(
        self,
        repository: BindingRepository,
        executor: ActionExecutor,
        normalizer: TextNormalizer,
        bus: EventBus,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._normalizer = normalizer
        self._bus = bus

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.RUN_BINDING:
            return self._run(intent, context)
        return self._learn(intent)

    def _run(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.binding_id is None:
            return SkillResult("Бінд не знайдено, сер.", success=False)
        binding = self._repository.get(intent.binding_id)
        if binding is None:
            return SkillResult("Бінд уже видалено, сер.", success=False)
        result = self._executor.execute(binding.action, context)
        if result.success:
            self._mark_used(binding)
        return SkillResult(result.reply, result.success, result.confirmation, learnable=False)

    def _mark_used(self, binding: Binding) -> None:
        if binding.id is None:
            return
        try:
            self._repository.mark_used(binding.id)
        except StorageError:
            logger.exception("Не вдалося оновити лічильник бінду")

    def _learn(self, intent: Intent) -> SkillResult:
        phrase = (intent.phrase or "").strip()
        if not phrase:
            return SkillResult("Не зрозумів, яку фразу запам'ятати, сер.", success=False)
        if not intent.actions:
            return SkillResult("Не зрозумів, що робити на цю фразу, сер.", success=False)
        action = intent.actions[0] if len(intent.actions) == 1 else Action(type=ActionType.MACRO, steps=intent.actions)
        description = describe_action(action)

        def save() -> SkillResult:
            return self._save(phrase, action)

        return SkillResult(
            f"Запам'ятати: коли ви кажете «{phrase}» — {description}. Підтверджуєте?",
            confirmation=PendingConfirmation(prompt=description, on_confirm=save),
            learnable=False,
        )

    def _save(self, phrase: str, action: Action) -> SkillResult:
        binding = Binding(
            id=None,
            phrase=phrase,
            normalized=self._normalizer.normalize(phrase),
            action=action,
            source=BindingSource.VOICE,
        )
        self._repository.save(binding)
        self._bus.publish(BindingsChanged())
        return SkillResult(f"Запам'ятав, сер. Кажіть «{phrase}».", learnable=False)
