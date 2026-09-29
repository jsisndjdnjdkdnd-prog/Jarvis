from __future__ import annotations

import logging

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import SkillError
from jarvis.core.intent import Action, Intent, IntentName
from jarvis.skills.actions import ActionExecutor

logger = logging.getLogger(__name__)

MAX_PLAN_STEPS = 6


class PlanSkill:
    name = "plan"
    intents = frozenset({IntentName.RUN_PLAN})

    def __init__(self, executor: ActionExecutor) -> None:
        self._executor = executor

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        actions = intent.actions[:MAX_PLAN_STEPS]
        if not actions:
            return SkillResult("Не зрозумів послідовність команд, сер.", success=False)
        replies: list[str] = []
        success = True
        for step, action in enumerate(actions):
            result = self._run(action, context)
            if result.confirmation is not None and step == 0:
                return result
            success = success and result.success
            replies.append(result.reply.rstrip("."))
        summary = ", потім ".join(dict.fromkeys(reply for reply in replies if reply))
        return SkillResult(f"{summary}." if summary else "Виконано, сер.", success=success, learnable=False)

    def _run(self, action: Action, context: DialogContext) -> SkillResult:
        try:
            return self._executor.execute(action, context)
        except SkillError as error:
            logger.warning("Крок плану %s не вдався: %s", action.describe(), error)
            return SkillResult(str(error), success=False)
