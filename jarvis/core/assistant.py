from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jarvis.core.context import DialogContext, ExchangeRecord, SkillResult
from jarvis.core.errors import JarvisError, StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    AssistantReplied,
    AssistantStateChanged,
    CommandHandled,
    CommandReceived,
    ConversationEnded,
    CorrectionRequested,
    ListenRequested,
    ShutdownRequested,
    SpeakRequested,
    SpeechInterruptRequested,
)
from jarvis.core.intent import Intent, IntentName, ResolutionStage
from jarvis.core.models import VocabularyAlias
from jarvis.core.speech_types import AssistantState, CommandSource, Utterance

logger = logging.getLogger(__name__)

NOT_UNDERSTOOD_REPLY = "Вибачте, сер, я не зрозумів команду."
FAILURE_REPLY = "Сталася помилка, сер. Деталі в журналі."
NOTHING_TO_CONFIRM_REPLY = "Немає чого підтверджувати, сер."
CORRECTION_REPLY = "Зрозумів, сер. Врахую на майбутнє."
CONTINUING_INTENTS: frozenset[IntentName] = frozenset(
    {IntentName.END_CONVERSATION, IntentName.STOP_SPEAKING, IntentName.SHUTDOWN_PC, IntentName.SLEEP_PC}
)
SILENT_INTENTS: frozenset[IntentName] = frozenset({IntentName.STOP_SPEAKING})
_STOP = object()


@dataclass(frozen=True)
class Interpretation:
    text: str
    normalized: str
    intent: Intent
    stage: ResolutionStage
    used_aliases: tuple[VocabularyAlias, ...]
    feedback: Callable[[bool], None]


class CommandInterpreter(Protocol):
    def interpret(self, text: str, utterance: Utterance | None) -> Interpretation | None: ...

    def normalize(self, text: str) -> str: ...

    def penalize(self, aliases: tuple[VocabularyAlias, ...]) -> None: ...


class IntentHandler(Protocol):
    def dispatch(self, intent: Intent, context: DialogContext) -> SkillResult: ...


class CommandRecorder(Protocol):
    def record(
        self,
        text: str,
        normalized: str,
        intent_json: str | None,
        stage: str | None,
        success: bool,
        reply: str,
    ) -> int: ...


@dataclass(frozen=True)
class _Outcome:
    result: SkillResult
    intent: Intent | None
    stage: ResolutionStage | None


class Assistant:
    def __init__(
        self,
        bus: EventBus,
        interpreter: CommandInterpreter,
        handler: IntentHandler,
        recorder: CommandRecorder,
        context: DialogContext,
    ) -> None:
        self._bus = bus
        self._interpreter = interpreter
        self._handler = handler
        self._recorder = recorder
        self._context = context
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._bus.subscribe(CommandReceived, self._queue.put)
        self._bus.subscribe(CorrectionRequested, self._queue.put)
        self._bus.subscribe(ShutdownRequested, lambda _: self.stop())
        self._thread = threading.Thread(target=self._run, name="assistant", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(_STOP)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            self._process_safely(item)

    def _process_safely(self, item: object) -> None:
        try:
            if isinstance(item, CommandReceived):
                self._process(item)
            elif isinstance(item, CorrectionRequested):
                self._finish(item_text="(виправлення)", source=CommandSource.TEXT, outcome=self._correct())
        except JarvisError as error:
            logger.error("Помилка обробки команди: %s", error)
            self._report_failure(item)
        except Exception:
            logger.exception("Неочікувана помилка обробки команди")
            self._report_failure(item)
        finally:
            self._bus.publish(AssistantStateChanged(AssistantState.IDLE))

    def _report_failure(self, item: object) -> None:
        self._reply(FAILURE_REPLY, success=False, follow_up=False)
        text = item.text if isinstance(item, CommandReceived) else "(виправлення)"
        self._bus.publish(CommandHandled(text, FAILURE_REPLY, None, None, False))

    def _process(self, command: CommandReceived) -> None:
        self._bus.publish(AssistantStateChanged(AssistantState.THINKING))
        interpretation = self._interpreter.interpret(command.text, command.utterance)
        pending_outcome = self._resolve_pending(interpretation)
        if pending_outcome is not None:
            self._finish(command.text, command.source, pending_outcome)
            return
        if interpretation is None:
            outcome = _Outcome(SkillResult(NOT_UNDERSTOOD_REPLY, success=False), None, None)
            self._finish(command.text, command.source, outcome)
            return
        outcome = self._execute(interpretation)
        self._finish(command.text, command.source, outcome, interpretation.normalized)

    def _resolve_pending(self, interpretation: Interpretation | None) -> _Outcome | None:
        if not self._context.has_pending_confirmation():
            return None
        intent_name = interpretation.intent.name if interpretation is not None else None
        if intent_name not in (IntentName.CONFIRM, IntentName.DENY):
            self._context.take_pending_confirmation()
            return None
        pending = self._context.take_pending_confirmation()
        if pending is None:
            return None
        if intent_name is IntentName.DENY:
            return _Outcome(SkillResult(pending.on_deny_reply), None, ResolutionStage.CONFIRMATION)
        self._bus.publish(AssistantStateChanged(AssistantState.EXECUTING))
        return _Outcome(pending.on_confirm(), None, ResolutionStage.CONFIRMATION)

    def _execute(self, interpretation: Interpretation) -> _Outcome:
        intent = interpretation.intent
        if intent.name is IntentName.CORRECTION:
            return self._correct()
        if intent.name is IntentName.STOP_SPEAKING:
            self._bus.publish(SpeechInterruptRequested())
            return _Outcome(SkillResult("", speak=False), intent, interpretation.stage)
        if intent.name in (IntentName.CONFIRM, IntentName.DENY):
            return _Outcome(SkillResult(NOTHING_TO_CONFIRM_REPLY, success=False), intent, interpretation.stage)
        self._bus.publish(AssistantStateChanged(AssistantState.EXECUTING))
        result = self._handler.dispatch(intent, self._context)
        self._context.remember_aliases(interpretation.used_aliases)
        interpretation.feedback(result.success and result.learnable)
        if result.confirmation is not None:
            self._context.set_pending_confirmation(result.confirmation)
        return _Outcome(result, intent, interpretation.stage)

    def _correct(self) -> _Outcome:
        aliases = self._context.take_last_aliases()
        if aliases:
            self._interpreter.penalize(aliases)
        return _Outcome(SkillResult(CORRECTION_REPLY), Intent(name=IntentName.CORRECTION), None)

    def _finish(
        self,
        item_text: str,
        source: CommandSource,
        outcome: _Outcome,
        normalized: str | None = None,
    ) -> None:
        result = outcome.result
        follow_up = self._should_continue(source, outcome)
        self._reply(result.reply, result.success, follow_up, speak=result.speak)
        if result.end_conversation:
            self._bus.publish(ConversationEnded())
        intent_name = outcome.intent.name.value if outcome.intent is not None else None
        stage = outcome.stage.value if outcome.stage is not None else None
        self._bus.publish(CommandHandled(item_text, result.reply, intent_name, stage, result.success))
        self._context.record_exchange(ExchangeRecord(item_text, outcome.intent, result.reply, result.success))
        try:
            self._recorder.record(
                text=item_text,
                normalized=normalized or self._interpreter.normalize(item_text),
                intent_json=outcome.intent.model_dump_json(exclude_none=True) if outcome.intent else None,
                stage=stage,
                success=result.success,
                reply=result.reply,
            )
        except StorageError:
            logger.exception("Не вдалося записати історію команд")

    def _should_continue(self, source: CommandSource, outcome: _Outcome) -> bool:
        if source is not CommandSource.VOICE:
            return False
        if outcome.result.confirmation is not None:
            return True
        if outcome.result.end_conversation:
            return False
        intent = outcome.intent
        if intent is not None and intent.name in CONTINUING_INTENTS:
            return False
        return self._context.conversation_mode

    def _reply(self, text: str, success: bool, follow_up: bool, speak: bool = True) -> None:
        self._bus.publish(AssistantReplied(text, success))
        if speak and text:
            self._bus.publish(SpeakRequested(text))
        if follow_up:
            self._bus.publish(ListenRequested(follow_up=True))
