from __future__ import annotations

from jarvis.core.intent import Intent, IntentName
from jarvis.nlu import lexicon_ext as lxe
from jarvis.nlu.prepared_text import PreparedText, Rule

MAX_SMALL_TALK_TOKENS = 9


class DialogueRules:
    def rules(self) -> tuple[Rule, ...]:
        return (
            self.stop_speaking,
            self.end_conversation,
            self.listen_mode,
            self.capabilities,
            self.repeat,
            self.small_talk,
        )

    def stop_speaking(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lxe.STOP_SPEAKING_PHRASES):
            return Intent(name=IntentName.STOP_SPEAKING)
        return None

    def end_conversation(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lxe.END_CONVERSATION_PHRASES):
            return Intent(name=IntentName.END_CONVERSATION)
        if len(prepared.tokens) <= 5 and prepared.contains(
            phrase for phrase in lxe.END_CONVERSATION_PHRASES if " " in phrase
        ):
            return Intent(name=IntentName.END_CONVERSATION)
        return None

    def listen_mode(self, prepared: PreparedText) -> Intent | None:
        if prepared.raw_contains(lxe.LISTEN_WAKE_PHRASES):
            return Intent(name=IntentName.LISTEN_MODE, mode="wake")
        if prepared.raw_contains(lxe.LISTEN_ALWAYS_PHRASES):
            return Intent(name=IntentName.LISTEN_MODE, mode="always")
        return None

    def capabilities(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lxe.CAPABILITIES_PHRASES) or prepared.contains(
            phrase for phrase in lxe.CAPABILITIES_PHRASES if " " in phrase
        ):
            return Intent(name=IntentName.CAPABILITIES)
        return None

    def repeat(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lxe.REPEAT_PHRASES):
            return Intent(name=IntentName.REPEAT)
        return None

    def small_talk(self, prepared: PreparedText) -> Intent | None:
        if len(prepared.tokens) > MAX_SMALL_TALK_TOKENS:
            return None
        for topic, phrases in lxe.SMALL_TALK_PHRASES.items():
            if prepared.equals(phrases) or prepared.contains(phrase for phrase in phrases if " " in phrase):
                return Intent(name=IntentName.SMALL_TALK, mode=topic.value, query=prepared.core)
        return None
