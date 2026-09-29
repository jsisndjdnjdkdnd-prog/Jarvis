from __future__ import annotations

from jarvis.core.assistant import Assistant, Interpretation
from jarvis.core.context import DialogContext, PendingConfirmation, SkillResult
from jarvis.core.event_bus import EventBus
from jarvis.core.events import AssistantReplied, CommandReceived, ListenRequested
from jarvis.core.intent import Intent, IntentName, ResolutionStage
from jarvis.core.models import VocabularyAlias
from jarvis.core.speech_types import CommandSource, Utterance

FIXED_INTENTS: dict[str, Intent] = {
    "вимкни комп'ютер": Intent(name=IntentName.SHUTDOWN_PC),
    "так": Intent(name=IntentName.CONFIRM),
    "ні": Intent(name=IntentName.DENY),
    "не те": Intent(name=IntentName.CORRECTION),
    "відкрий хром": Intent(name=IntentName.OPEN_APP, target="хром"),
}


class FakeInterpreter:
    def __init__(self) -> None:
        self.feedback: list[bool] = []
        self.penalized: list[tuple[VocabularyAlias, ...]] = []

    def normalize(self, text: str) -> str:
        return text

    def interpret(self, text: str, utterance: Utterance | None) -> Interpretation | None:
        intent = FIXED_INTENTS.get(text)
        if intent is None:
            return None
        alias = VocabularyAlias(id=7, word_id=1, alias="хром", normalized="хром")
        return Interpretation(text, text, intent, ResolutionStage.RULES, (alias,), self.feedback.append)

    def penalize(self, aliases: tuple[VocabularyAlias, ...]) -> None:
        self.penalized.append(aliases)


class FakeHandler:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def dispatch(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.SHUTDOWN_PC:
            def confirm() -> SkillResult:
                self.executed.append("shutdown")
                return SkillResult("Виконую.")

            return SkillResult("Ви впевнені?", confirmation=PendingConfirmation("вимкнути", confirm), learnable=False)
        self.executed.append(intent.name.value)
        return SkillResult("Відкриваю хром.")


class FakeRecorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, bool]] = []

    def record(self, text: str, normalized: str, intent_json: str | None, stage: str | None, success: bool, reply: str) -> int:
        self.records.append((text, success))
        return len(self.records)


class Harness:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.interpreter = FakeInterpreter()
        self.handler = FakeHandler()
        self.recorder = FakeRecorder()
        self.replies: list[str] = []
        self.listen_requests = 0
        self.bus.subscribe(AssistantReplied, lambda event: self.replies.append(event.text))
        self.bus.subscribe(ListenRequested, lambda _: self._count_listen())
        self.assistant = Assistant(self.bus, self.interpreter, self.handler, self.recorder, DialogContext())

    def _count_listen(self) -> None:
        self.listen_requests += 1

    def say(self, text: str, source: CommandSource = CommandSource.VOICE) -> None:
        self.assistant._process_safely(CommandReceived(text, source))
        while not self.bus._queue.empty():
            self.bus.dispatch_now(self.bus._queue.get())


def test_confirmation_flow_executes_after_yes() -> None:
    harness = Harness()
    harness.say("вимкни комп'ютер")
    assert harness.handler.executed == []
    assert harness.replies[-1] == "Ви впевнені?"
    assert harness.listen_requests == 1
    harness.say("так")
    assert harness.handler.executed == ["shutdown"]
    assert harness.replies[-1] == "Виконую."


def test_confirmation_denied() -> None:
    harness = Harness()
    harness.say("вимкни комп'ютер")
    harness.say("ні")
    assert harness.handler.executed == []
    assert harness.replies[-1] == "Скасовано, сер."


def test_other_command_drops_pending_confirmation() -> None:
    harness = Harness()
    harness.say("вимкни комп'ютер")
    harness.say("відкрий хром")
    harness.say("так")
    assert harness.handler.executed == ["open_app"]
    assert harness.replies[-1] == "Немає чого підтверджувати, сер."


def test_unknown_command_reply_and_history() -> None:
    harness = Harness()
    harness.say("абракадабра")
    assert "не зрозумів" in harness.replies[-1]
    assert harness.recorder.records == [("абракадабра", False)]


def test_success_triggers_learning_and_correction_penalizes() -> None:
    harness = Harness()
    harness.say("відкрий хром", CommandSource.TEXT)
    assert harness.interpreter.feedback == [True]
    harness.say("не те")
    assert harness.interpreter.penalized[0][0].alias == "хром"
