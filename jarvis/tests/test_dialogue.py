from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import pytest

from jarvis.core.config import DeepSeekSection, DialogueSection
from jarvis.core.context import DialogContext, ExchangeRecord
from jarvis.core.errors import DeepSeekError, InvalidModelResponseError
from jarvis.core.intent import (
    Intent,
    IntentName,
    SmallTalkTopic,
    SystemInfoKind,
    WeatherPeriod,
    WindowCommand,
    YouTubeCommand,
)
from jarvis.core.models import Program, ProgramKind, Track
from jarvis.nlu.deepseek_client import ChatRole, ChatTurn, DeepSeekClient
from jarvis.nlu.deepseek_intents import (
    NON_RESOLVABLE_INTENTS,
    DeepSeekIntentResolver,
    build_intent_system_prompt,
    resolvable_intents,
)
from jarvis.nlu.dialogue import TOPIC_HINTS, DialogueEngine, clean_spoken_text, limit_sentences
from jarvis.skills.conversation import (
    CAPABILITIES_REPLIES,
    CHAT_FALLBACKS,
    FAREWELLS,
    GOODNIGHT_DAYTIME,
    GOODNIGHT_LATE,
    GREETINGS,
    JOKES,
    NIGHT_FAREWELLS,
    NOTHING_TO_REPEAT,
    THANKS_REPLIES,
    ConversationSkill,
    DayPeriod,
    DialogueStatus,
    PhrasePicker,
    small_talk_replies,
)
from jarvis.storage.repositories import Repositories

T = TypeVar("T")

AFTERNOON = datetime(2026, 9, 29, 14, 5)
MORNING = datetime(2026, 9, 29, 8, 30)
NIGHT = datetime(2026, 9, 29, 2, 15)


@dataclass(frozen=True)
class ChatCall:
    system_prompt: str
    user_prompt: str
    purpose: str
    temperature: float | None
    prior_messages: tuple[ChatTurn, ...]


class FakeChatClient:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        error: DeepSeekError | None = None,
        available: bool = True,
    ) -> None:
        self.calls: list[ChatCall] = []
        self._response = response if response is not None else {"reply": "Звісно, сер."}
        self._error = error
        self._available = available

    @property
    def available(self) -> bool:
        return self._available

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        purpose: str,
        parse: Callable[[dict[str, Any]], T],
        *,
        temperature: float | None = None,
        prior_messages: Sequence[ChatTurn] = (),
    ) -> T:
        self.calls.append(ChatCall(system_prompt, user_prompt, purpose, temperature, tuple(prior_messages)))
        if self._error is not None:
            raise self._error
        try:
            return parse(self._response)
        except ValueError as error:
            raise InvalidModelResponseError(str(error)) from error


class RecordingClient(DeepSeekClient):
    def __init__(self, settings: DeepSeekSection, repositories: Repositories) -> None:
        super().__init__(settings, "test-key", repositories.deepseek_stats)
        self.requests: list[tuple[list[dict[str, str]], float]] = []

    def _request(self, messages: list[dict[str, str]], purpose: str, temperature: float) -> str:
        self.requests.append((list(messages), temperature))
        return '{"reply": "Добре, сер."}'


def exchange(text: str, reply: str, intent: Intent | None = None) -> ExchangeRecord:
    return ExchangeRecord(text=text, intent=intent, reply=reply, success=True)


def engine(
    client: FakeChatClient,
    history: Sequence[ExchangeRecord] = (),
    settings: DialogueSection | None = None,
    clock: datetime = AFTERNOON,
    status: Callable[[], dict[str, str]] | None = None,
) -> DialogueEngine:
    return DialogueEngine(client, lambda: tuple(history), settings or DialogueSection(), lambda: clock, status)


def skill(
    client: FakeChatClient | None = None,
    settings: DialogueSection | None = None,
    clock: datetime = AFTERNOON,
) -> ConversationSkill:
    resolved = settings or DialogueSection()
    dialogue = engine(client, settings=resolved, clock=clock) if client is not None else None
    return ConversationSkill(dialogue, resolved, lambda: clock, random.Random(7))


def test_system_prompt_has_persona_time_and_status() -> None:
    client = FakeChatClient()
    status = {"Now playing": "Imagine Dragons — Believer", "Idle": " "}
    engine(client, status=lambda: status).reply("як справи")
    call = client.calls[0]
    for fragment in ("J.A.R.V.I.S.", "Tony Stark", "Ukrainian", '"сер"', "at most 3 short sentences", "JSON"):
        assert fragment in call.system_prompt
    assert "Tuesday, 2026-09-29 14:05" in call.system_prompt
    assert "Now playing: Imagine Dragons — Believer." in call.system_prompt
    assert "Idle" not in call.system_prompt
    assert "Never claim" in call.system_prompt
    assert call.purpose == "chat"
    assert call.temperature == DialogueSection().temperature


def test_history_is_sent_as_prior_messages() -> None:
    client = FakeChatClient()
    history = [
        exchange("перше", "Відповідь перша."),
        exchange("друге", "Відповідь друга."),
        exchange("мовчи", ""),
        exchange("третє", "Відповідь третя."),
    ]
    engine(client, history, DialogueSection(history_turns=2)).reply("четверте")
    turns = client.calls[0].prior_messages
    assert [turn.role for turn in turns] == [ChatRole.USER, ChatRole.ASSISTANT] * 2
    assert [turn.content for turn in turns if turn.role is ChatRole.USER] == ["друге", "третє"]
    assert json.loads(turns[-1].content) == {"reply": "Відповідь третя."}
    assert client.calls[0].user_prompt == "четверте"


def test_history_disabled_when_turns_zero() -> None:
    client = FakeChatClient()
    engine(client, [exchange("привіт", "Вітаю, сер.")], DialogueSection(history_turns=0)).reply("як ти")
    assert client.calls[0].prior_messages == ()


def test_topic_hint_is_added_to_user_message() -> None:
    client = FakeChatClient()
    engine(client).reply("розкажи   жарт", SmallTalkTopic.JOKE.value)
    prompt = client.calls[0].user_prompt
    assert prompt.startswith("розкажи жарт\n")
    assert "Topic: joke" in prompt
    assert TOPIC_HINTS[SmallTalkTopic.JOKE] in prompt


def test_every_topic_has_a_hint() -> None:
    assert set(TOPIC_HINTS) == set(SmallTalkTopic)


def test_reply_is_cleaned_for_speech() -> None:
    client = FakeChatClient({"reply": "Джарвіс: **Звісно**, сер. *посміхається* Все під контролем 😊"})
    assert engine(client).reply("все гаразд?") == "Звісно, сер. Все під контролем"


def test_clean_spoken_text_handles_lists_and_quotes() -> None:
    assert clean_spoken_text("«Добрий вечір, сер.»") == "Добрий вечір, сер."
    assert clean_spoken_text("Варіанти:\n- музика\n- гра") == "Варіанти: музика гра"
    assert clean_spoken_text("[сміється] Тонко, сер.") == "Тонко, сер."


def test_reply_is_limited_in_sentences() -> None:
    client = FakeChatClient({"reply": "Раз. Два! Три? Чотири. П'ять."})
    settings = DialogueSection(max_reply_sentences=2)
    assert engine(client, settings=settings).reply("рахуй") == "Раз. Два! Три?"
    assert limit_sentences("Один. Два.", 5) == "Один. Два."


def test_empty_reply_is_rejected() -> None:
    client = FakeChatClient({"reply": " ** "})
    with pytest.raises(InvalidModelResponseError):
        engine(client).reply("що")


def test_client_errors_propagate() -> None:
    client = FakeChatClient(error=DeepSeekError("offline"))
    with pytest.raises(DeepSeekError):
        engine(client).reply("що")


def test_available_follows_client() -> None:
    assert engine(FakeChatClient(available=False)).available is False
    assert engine(FakeChatClient()).available is True


def test_deepseek_client_uses_temperature_and_prior_messages(repositories: Repositories) -> None:
    client = RecordingClient(DeepSeekSection(temperature=0.0), repositories)
    turns = (ChatTurn(ChatRole.USER, "привіт"), ChatTurn(ChatRole.ASSISTANT, '{"reply": "Вітаю."}'))
    result = client.complete_json("system", "user", "chat", lambda data: data["reply"], temperature=0.7, prior_messages=turns)
    messages, temperature = client.requests[0]
    assert result == "Добре, сер."
    assert temperature == 0.7
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    client.complete_json("system", "user", "intent", lambda data: data)
    assert client.requests[1][1] == 0.0


def test_chat_prefers_resolver_reply() -> None:
    client = FakeChatClient()
    result = skill(client).handle(
        Intent(name=IntentName.CHAT, reply="Сорок два, сер.", query="сенс життя"), DialogContext()
    )
    assert result.reply == "Сорок два, сер."
    assert result.learnable is False
    assert client.calls == []


def test_chat_asks_dialogue_engine() -> None:
    client = FakeChatClient({"reply": "Це дуже далека й дуже яскрава галактика, сер."})
    result = skill(client).handle(Intent(name=IntentName.CHAT, query="що таке квазар"), DialogContext())
    assert result.reply == "Це дуже далека й дуже яскрава галактика, сер."
    assert result.success is True
    assert result.learnable is False
    assert client.calls[0].user_prompt == "що таке квазар"


def test_chat_falls_back_when_client_fails() -> None:
    result = skill(FakeChatClient(error=DeepSeekError("offline"))).handle(
        Intent(name=IntentName.CHAT, message="розкажи про чорні діри"), DialogContext()
    )
    assert result.reply in CHAT_FALLBACKS
    assert result.success is False
    assert result.learnable is False


def test_chat_falls_back_when_unavailable_or_missing() -> None:
    client = FakeChatClient(available=False)
    unavailable = skill(client).handle(Intent(name=IntentName.CHAT, query="як справи у світі"), DialogContext())
    missing = skill(None).handle(Intent(name=IntentName.CHAT, query="як справи у світі"), DialogContext())
    assert unavailable.reply in CHAT_FALLBACKS
    assert missing.reply in CHAT_FALLBACKS
    assert client.calls == []


def test_small_talk_uses_dialogue_with_topic() -> None:
    client = FakeChatClient({"reply": "Штучний інтелект заходить у бар. Бармен каже: у нас тут не обслуговують ботів."})
    result = skill(client).handle(
        Intent(name=IntentName.SMALL_TALK, mode=SmallTalkTopic.JOKE.value, query="розкажи жарт"), DialogContext()
    )
    assert result.reply.startswith("Штучний інтелект")
    assert "Topic: joke" in client.calls[0].user_prompt
    assert result.learnable is False


def test_small_talk_offline_when_llm_disabled() -> None:
    client = FakeChatClient()
    result = skill(client, DialogueSection(llm_small_talk=False)).handle(
        Intent(name=IntentName.SMALL_TALK, mode=SmallTalkTopic.JOKE.value, query="розкажи жарт"), DialogContext()
    )
    assert result.reply in JOKES
    assert client.calls == []


def test_small_talk_falls_back_to_offline_bank_on_error() -> None:
    result = skill(FakeChatClient(error=DeepSeekError("offline"))).handle(
        Intent(name=IntentName.SMALL_TALK, mode=SmallTalkTopic.MOOD.value, query="як справи"), DialogContext()
    )
    assert result.reply in small_talk_replies(SmallTalkTopic.MOOD, DayPeriod.DAY)
    assert result.learnable is False


def test_small_talk_unknown_mode_is_generic() -> None:
    result = skill(None).handle(Intent(name=IntentName.SMALL_TALK, mode="weird", query="ну"), DialogContext())
    assert result.reply in small_talk_replies(SmallTalkTopic.GENERIC, DayPeriod.DAY)


@pytest.mark.parametrize("period", list(DayPeriod))
@pytest.mark.parametrize("topic", list(SmallTalkTopic))
def test_every_topic_has_varied_offline_replies(topic: SmallTalkTopic, period: DayPeriod) -> None:
    replies = small_talk_replies(topic, period)
    assert len(replies) >= 6
    assert len(set(replies)) == len(replies)
    for reply in replies:
        assert reply.strip() == reply
        assert reply[-1] in ".!?»"
        assert clean_spoken_text(reply) == reply


def test_joke_bank_is_large() -> None:
    assert len(JOKES) >= 10
    assert len(set(JOKES)) == len(JOKES)


def test_goodnight_is_time_aware() -> None:
    morning = small_talk_replies(SmallTalkTopic.GOODNIGHT, DayPeriod.MORNING)
    night = small_talk_replies(SmallTalkTopic.GOODNIGHT, DayPeriod.NIGHT)
    assert set(GOODNIGHT_DAYTIME) <= set(morning)
    assert not set(GOODNIGHT_LATE) & set(morning)
    assert set(GOODNIGHT_LATE) <= set(night)
    reply = skill(None, clock=MORNING).handle(
        Intent(name=IntentName.SMALL_TALK, mode=SmallTalkTopic.GOODNIGHT.value, query="на добраніч"), DialogContext()
    ).reply
    assert reply in morning


def test_greeting_depends_on_time_of_day() -> None:
    morning = skill(None, clock=MORNING).handle(Intent(name=IntentName.GREETING), DialogContext())
    night = skill(None, clock=NIGHT).handle(Intent(name=IntentName.GREETING), DialogContext())
    assert morning.reply in GREETINGS[DayPeriod.MORNING]
    assert night.reply in GREETINGS[DayPeriod.NIGHT]
    assert morning.learnable is False


def test_thanks_reply() -> None:
    result = skill(None).handle(Intent(name=IntentName.THANKS), DialogContext())
    assert result.reply in THANKS_REPLIES
    assert result.learnable is False


def test_capabilities_summary() -> None:
    result = skill(None).handle(Intent(name=IntentName.CAPABILITIES), DialogContext())
    assert result.reply in CAPABILITIES_REPLIES
    for variant in CAPABILITIES_REPLIES:
        assert limit_sentences(variant, 3) == variant
        for keyword in ("ютуб", "таймери", "погод", "скриншот", "фраз"):
            assert keyword in variant.lower()


def test_repeat_returns_last_non_repeat_reply() -> None:
    context = DialogContext()
    context.record_exchange(exchange("відкрий хром", "Відкриваю Chrome.", Intent(name=IntentName.OPEN_APP)))
    context.record_exchange(exchange("котра година", "Чотирнадцята нуль п'ять.", Intent(name=IntentName.TIME_NOW)))
    context.record_exchange(exchange("повтори", "Повтор.", Intent(name=IntentName.REPEAT)))
    context.record_exchange(exchange("замовкни", "", Intent(name=IntentName.STOP_SPEAKING)))
    result = skill(None).handle(Intent(name=IntentName.REPEAT), context)
    assert result.reply == "Чотирнадцята нуль п'ять."
    assert result.learnable is False


def test_repeat_without_history() -> None:
    assert skill(None).handle(Intent(name=IntentName.REPEAT), DialogContext()).reply == NOTHING_TO_REPEAT


def test_end_conversation_ends_dialogue() -> None:
    result = skill(None).handle(Intent(name=IntentName.END_CONVERSATION), DialogContext())
    assert result.end_conversation is True
    assert result.learnable is False
    assert result.reply in FAREWELLS
    night = skill(None, clock=NIGHT).handle(Intent(name=IntentName.END_CONVERSATION), DialogContext())
    assert night.reply in FAREWELLS + NIGHT_FAREWELLS


def test_skill_declares_dialogue_intents() -> None:
    assert skill(None).intents == frozenset(
        {
            IntentName.GREETING,
            IntentName.THANKS,
            IntentName.CHAT,
            IntentName.SMALL_TALK,
            IntentName.CAPABILITIES,
            IntentName.REPEAT,
            IntentName.END_CONVERSATION,
        }
    )


def test_phrase_picker_avoids_immediate_repeats() -> None:
    picker = PhrasePicker(random.Random(3))
    options = ("а", "б", "в", "г")
    picks = [picker.pick("key", options) for _ in range(30)]
    assert all(first != second for first, second in zip(picks, picks[1:], strict=False))
    assert picker.pick("single", ("один",)) == "один"
    assert picker.pick("single", ("один",)) == "один"


def test_dialogue_status_reports_context() -> None:
    context = DialogContext()
    track = Track(title="Believer", artist="Imagine Dragons", url="https://soundcloud.com/x")
    context.remember_track(track)
    context.remember_program(Program(None, "Google Chrome", "google chrome", "chrome.exe", ProgramKind.EXECUTABLE, "test"))
    assert DialogueStatus(context)() == {
        "Last played track": "Imagine Dragons — Believer",
        "Last opened program": "Google Chrome",
    }
    assert DialogueStatus(context, lambda: track)()["Now playing"] == "Imagine Dragons — Believer"


def test_intent_prompt_lists_every_intent_value() -> None:
    prompt = build_intent_system_prompt(AFTERNOON)
    assert set(resolvable_intents()) | NON_RESOLVABLE_INTENTS == set(IntentName)
    for name in resolvable_intents():
        assert f"- {name.value}:" in prompt
    for name in IntentName:
        assert name.value in prompt


def test_intent_prompt_lists_enum_modes() -> None:
    prompt = build_intent_system_prompt(AFTERNOON)
    for values in (SmallTalkTopic, YouTubeCommand, WindowCommand, SystemInfoKind, WeatherPeriod):
        for member in values:
            assert f"'{member.value}'" in prompt
    assert "J.A.R.V.I.S." in prompt
    assert "'сер'" in prompt
    assert "speech recognition" in prompt


def test_resolver_includes_recent_history() -> None:
    history = (
        exchange("відкрий хром", "Відкриваю Chrome.", Intent(name=IntentName.OPEN_APP, target="хром")),
        exchange("яка погода", "У Києві плюс п'ятнадцять.", Intent(name=IntentName.WEATHER, mode="now")),
        exchange("замовкни", "", Intent(name=IntentName.STOP_SPEAKING)),
    )
    client = FakeChatClient({"name": "weather", "mode": "tomorrow", "uses_history": True})
    resolver = DeepSeekIntentResolver(client, lambda: AFTERNOON, lambda: history, history_turns=2)
    resolved = resolver.resolve_detailed("а завтра?")
    prompt = client.calls[0].user_prompt
    assert "User: яка погода  [weather mode=now]" in prompt
    assert "Jarvis: У Києві плюс п'ятнадцять." in prompt
    assert "User: замовкни" in prompt
    assert "відкрий хром" not in prompt
    assert prompt.endswith("Command: а завтра?")
    assert client.calls[0].purpose == "intent"
    assert resolved.intent == Intent(name=IntentName.WEATHER, mode="tomorrow")
    assert resolved.uses_history is True


def test_resolver_without_history_keeps_plain_prompt() -> None:
    client = FakeChatClient({"name": "open_app", "target": "хром", "uses_history": True})
    resolver = DeepSeekIntentResolver(client, lambda: AFTERNOON)
    resolved = resolver.resolve_detailed("відкрий хром")
    assert client.calls[0].user_prompt == "Command: відкрий хром"
    assert resolved.uses_history is False
    assert resolver.resolve("відкрий хром") == Intent(name=IntentName.OPEN_APP, target="хром")


def test_resolver_parsing_drops_internal_fields_and_cleans_reply() -> None:
    client = FakeChatClient(
        {
            "name": "chat",
            "reply": "**Сорок два**, сер.",
            "query": "сенс життя",
            "target": None,
            "binding_id": 5,
            "actions": [{"type": "shell", "target": "rm"}],
        }
    )
    intent = DeepSeekIntentResolver(client).resolve("сенс життя")
    assert intent == Intent(name=IntentName.CHAT, reply="Сорок два, сер.", query="сенс життя")
