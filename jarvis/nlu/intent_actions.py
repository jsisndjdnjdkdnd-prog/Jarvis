from __future__ import annotations

from jarvis.core.intent import Action, ActionType, Intent, IntentName

VOLATILE_INTENTS: frozenset[IntentName] = frozenset(
    {
        IntentName.REMINDER_ADD,
        IntentName.TIMER_SET,
        IntentName.LEARN_BINDING,
        IntentName.RUN_BINDING,
        IntentName.CONFIRM,
        IntentName.DENY,
        IntentName.CORRECTION,
        IntentName.CHAT,
        IntentName.UNKNOWN,
        IntentName.PLAY_RECOMMENDED,
        IntentName.SHUTDOWN_PC,
        IntentName.RESTART_PC,
    }
)


class IntentActionMapper:
    def to_action(self, intent: Intent) -> Action:
        if intent.name is IntentName.OPEN_APP and intent.target:
            return Action(type=ActionType.OPEN_APP, target=intent.target)
        if intent.name is IntentName.CLOSE_APP and intent.target:
            return Action(type=ActionType.CLOSE_PROCESS, target=intent.target)
        if intent.name is IntentName.OPEN_FOLDER and intent.target:
            return Action(type=ActionType.OPEN_FOLDER, target=intent.target)
        if intent.name is IntentName.OPEN_URL and intent.target:
            return Action(type=ActionType.LAUNCH, target=intent.target)
        if intent.name is IntentName.PLAY_MUSIC and intent.query:
            return Action(type=ActionType.PLAY_TRACK, target=intent.query)
        return Action(type=ActionType.INTENT, intent=intent.with_updates(confidence=1.0))

    def is_learnable(self, intent: Intent) -> bool:
        if intent.name in VOLATILE_INTENTS:
            return False
        if intent.name is IntentName.CLOSE_APP and not intent.target:
            return False
        return intent.when is None and intent.duration_seconds is None
