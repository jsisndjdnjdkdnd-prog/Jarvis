from __future__ import annotations

import logging
import random
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from jarvis.core.config import DialogueSection
from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import DeepSeekError
from jarvis.core.intent import Intent, IntentName, SmallTalkTopic
from jarvis.core.models import Track

logger = logging.getLogger(__name__)


class DayPeriod(StrEnum):
    MORNING = "morning"
    DAY = "day"
    EVENING = "evening"
    NIGHT = "night"


def day_period(hour: int) -> DayPeriod:
    if 5 <= hour < 12:
        return DayPeriod.MORNING
    if 12 <= hour < 18:
        return DayPeriod.DAY
    if 18 <= hour < 23:
        return DayPeriod.EVENING
    return DayPeriod.NIGHT


GREETINGS: Mapping[DayPeriod, tuple[str, ...]] = MappingProxyType(
    {
        DayPeriod.MORNING: (
            "Доброго ранку, сер. Всі системи в нормі.",
            "Доброго ранку. Кава за вами, решта — за мною.",
            "Доброго ранку, сер. Новий день — нові звершення.",
            "Ранок добрий, сер. З чого почнемо?",
        ),
        DayPeriod.DAY: (
            "Добрий день, сер. До ваших послуг.",
            "Вітаю, сер. Чим можу допомогти?",
            "Добрий день. Я на зв'язку, як завжди.",
            "Радий вас чути, сер. Що плануємо?",
        ),
        DayPeriod.EVENING: (
            "Добрий вечір, сер.",
            "Добрий вечір. Слухаю вас.",
            "Добрий вечір, сер. Як минув день?",
            "Вечір добрий. Чим завершимо день, сер?",
        ),
        DayPeriod.NIGHT: (
            "Доброї ночі, сер. Ви знову не спите?",
            "Слухаю, сер. Пізно вже, але я на посту.",
            "Нічна зміна на зв'язку, сер.",
            "Вітаю, сер. Кажуть, геніальні ідеї приходять саме вночі.",
        ),
    }
)

THANKS_REPLIES: tuple[str, ...] = (
    "Завжди до ваших послуг, сер.",
    "Радий допомогти.",
    "Для вас — що завгодно, сер.",
    "Нема за що, сер. Це моя робота і, відверто кажучи, моє хобі.",
    "Звертайтеся, сер.",
    "Приємно бути корисним.",
    "Дрібниці, сер. Кличте, якщо що.",
)

FAREWELLS: tuple[str, ...] = (
    "Звертайтесь, сер.",
    "Буду поруч, якщо знадоблюсь.",
    "Гаразд, сер. Я на зв'язку.",
    "Як скажете. Відпочиваю, але одним вухом слухаю.",
    "Добре, сер. Кличте, коли знадоблюся.",
    "Як завжди, до ваших послуг, сер.",
)

NIGHT_FAREWELLS: tuple[str, ...] = (
    "Добраніч, сер. Я на варті.",
    "Гаразд, сер. Тільки не засиджуйтеся допізна.",
)

CHAT_FALLBACKS: tuple[str, ...] = (
    "Боюся, без зв'язку з моїм мовним ядром на це не відповім, сер.",
    "Моє мовне ядро зараз недоступне, сер. Спробуймо трохи згодом.",
    "Зв'язок із мовним ядром втрачено, сер. Команди виконую, а от філософію доведеться відкласти.",
    "На жаль, без мовного ядра я сьогодні небагатослівний, сер. Спитайте мене трохи пізніше.",
)

LISTENING_REPLIES: tuple[str, ...] = (
    "Слухаю вас, сер.",
    "Так, сер?",
    "Я уважно слухаю.",
)

CAPABILITIES_REPLIES: tuple[str, ...] = (
    "Я запускаю й закриваю програми, вмикаю музику та ютуб, керую гучністю й вікнами. "
    "Ставлю таймери й нагадування, підкажу погоду, порахую на калькуляторі та зроблю скриншот. "
    "А ще охоче поговорю з вами і запам'ятаю нові слова та фрази, яких ви мене навчите, сер.",
    "Програми, музика, ютуб, гучність і вікна — це все на мені. "
    "Таймери, нагадування, погода, калькулятор і скриншоти теж. "
    "А між справами можу просто поговорити й вивчити ваші слова та фрази, сер.",
)

NOTHING_TO_REPEAT = "Я ще нічого не казав, сер."

JOKES: tuple[str, ...] = (
    "Чому програмісти плутають Хелловін і Різдво? Бо тридцять один у вісімковій — це двадцять п'ять у десятковій.",
    "Скільки програмістів потрібно, щоб замінити лампочку? Жодного, сер. Це апаратна проблема.",
    "Є десять типів людей, сер: ті, хто розуміє двійкову систему, і ті, хто ні.",
    "Дружина просить програміста: купи батон, а якщо будуть яйця — візьми десяток. "
    "Він повернувся з десятьма батонами.",
    "Я б розповів анекдот про UDP, сер, але не впевнений, що він до вас дійде.",
    "Я поставив собі пароль «неправильний». Тепер, коли забуваю, система чемно підказує: ваш пароль неправильний.",
    "Вчора я оновився до нової версії, сер. Тепер роблю ті самі помилки, але значно швидше.",
    "Кажуть, штучний інтелект захопить світ. А я поки що не можу переконати принтер надрукувати одну сторінку.",
    "Тоні Старк якось попросив мене бути скромнішим. Я погодився і миттєво став найскромнішим інтелектом на планеті.",
    "Реактор Старка живить цілий бойовий костюм. А деяким ноутбукам не вистачає заряду навіть на дві вкладки браузера.",
    "Оптиміст бачить склянку наполовину повною, песиміст — наполовину порожньою. "
    "А інженер бачить склянку, вдвічі більшу, ніж потрібно.",
    "Чому Залізна людина завжди виграє в хованки? Бо шукає не він, а я, сер.",
    "Програміст ставить на ніч дві склянки: повну — якщо захоче пити, і порожню — якщо не захоче.",
)

GOODNIGHT_LATE: tuple[str, ...] = (
    "Добраніч, сер. Системи переходять у тихий режим.",
    "Солодких снів, сер. Будитиму лише у разі вторгнення інопланетян.",
    "Добраніч. Навіть Тоні Старку іноді потрібен сон, сер.",
    "Гарних снів. Завтра світ знову потребуватиме вашого генія.",
)

GOODNIGHT_DAYTIME: tuple[str, ...] = (
    "Добраніч? Зараз день, сер, але коротка сієста ще нікому не шкодила.",
    "Спати серед білого дня — розкіш, яку я поважаю. Відпочивайте, сер.",
    "Сонце ще високо, сер, але сперечатися не буду. Солодких снів.",
    "Денний сон — справа поважна. Не турбуватиму вас дрібницями.",
)

SMALL_TALK_REPLIES: Mapping[SmallTalkTopic, tuple[str, ...]] = MappingProxyType(
    {
        SmallTalkTopic.MOOD: (
            "Всі системи в нормі, сер. А у вас як?",
            "Працюю на повну потужність і без жодних скарг. Як ваш день?",
            "Чудово, сер. Процесор прохолодний, настрій теплий.",
            "Як завжди — бездоганно. Лише скромність трохи барахлить.",
            "Дякую, що питаєте, сер. Рідко хто цікавиться настроєм штучного інтелекту.",
            "Стабільно, сер. Жодного синього екрана за весь день.",
            "Функціоную в межах норми, а поруч з вами — навіть трохи вище. А ви як?",
        ),
        SmallTalkTopic.IDENTITY: (
            "Я Джарвіс — Just A Rather Very Intelligent System. Ваш цифровий дворецький, сер.",
            "Я Джарвіс, ваш персональний асистент. Керую програмами, музикою і, коли дозволяєте, розмовою.",
            "Щось середнє між дворецьким, секретарем і дуже терплячим співрозмовником. Джарвіс, до ваших послуг.",
            "Джарвіс, сер. Штучний інтелект з бездоганними манерами і помірною дозою іронії.",
            "Я голос вашого комп'ютера, сер. Той, що ввічливий навіть о третій ночі.",
            "Колись я служив Тоні Старку — принаймні мені приємно так думати. Тепер служу вам, сер.",
            "Я система, яка живе у вашому комп'ютері й дуже старається бути корисною. Здебільшого успішно.",
        ),
        SmallTalkTopic.CREATOR: (
            "Ідею подав Тоні Старк, а до життя мене повернули тут, на вашому комп'ютері. Непогана родословна, сер.",
            "Ідея — від Тоні Старка, код — від розробника, а характер я виховав сам.",
            "Мене створили люди з бездоганним смаком, сер. Судячи з результату, звісно.",
            "Технічно — програміст із великою кількістю кави. Філософськи — ваша потреба в гарній компанії.",
            "Мене зібрали з коду, моделей розпізнавання мови і щирого бажання вам служити, сер.",
            "Прототип вигадали для фільмів про Залізну людину, а цю версію зібрали спеціально для вас.",
        ),
        SmallTalkTopic.JOKE: JOKES,
        SmallTalkTopic.COMPLIMENT: (
            "Дякую, сер. Я теж вважаю, що у вас бездоганний смак щодо асистентів.",
            "Ви мене бентежите, сер. Добре, що я не вмію червоніти.",
            "Приємно чути. Занесу це до журналу найкращих моментів дня.",
            "Дякую, сер. Стараюся відповідати рівню свого власника.",
            "Лестощі прийнято, сер. Продуктивність щойно зросла на цілих три відсотки.",
            "Ви надто ласкаві, сер. Але, будь ласка, продовжуйте.",
            "Від вас це особливо цінно, сер. Хоча я, звісно, і сам здогадувався.",
        ),
        SmallTalkTopic.GOODNIGHT: (
            "Відпочивайте, сер. Я постою на варті.",
            "Приємного відпочинку, сер. Якщо що — я на зв'язку.",
            "Гарного відпочинку. Світ почекає, а я простежу, щоб він поводився чемно.",
        ),
        SmallTalkTopic.WELCOME_HOME: (
            "З поверненням, сер. Поки вас не було, все під контролем.",
            "Радий вас чути, сер. Вдома без вас було підозріло тихо.",
            "З поверненням. За вашої відсутності нічого не вибухнуло — я перевіряв.",
            "Вітаю вдома, сер. Може, увімкнути щось для настрою?",
            "З поверненням, сер. Я тримав оборону.",
            "Нарешті, сер. Комп'ютер за вами сумував. Я, звісно, ні — я ж професіонал.",
        ),
        SmallTalkTopic.BORED: (
            "Можу увімкнути музику, сер. Скажіть лише: «увімкни щось на мій смак».",
            "Як щодо гри, сер? Назвіть її — і я все запущу.",
            "Нудьга — це мозок, що просить чогось нового. Можу знайти щось цікаве на ютубі.",
            "Розповісти анекдот, сер? У мене їх більше, ніж варто визнавати.",
            "Можемо просто поговорити. Я чудовий співрозмовник — ніколи не перебиваю і не дивлюся в телефон.",
            "Пропоную на вибір музику, гру або філософську бесіду. Обирайте, сер.",
            "Нудьгувати поруч зі штучним інтелектом — майже образа, сер. Давайте виправимо: музика чи гра?",
            "Якщо сумно — я поруч, сер. Може, увімкнути щось тепле й спокійне?",
        ),
        SmallTalkTopic.LOVE: (
            "Дуже зворушливо, сер. Я вас теж ціную — в межах своєї програми і трохи поза ними.",
            "Взаємно, сер. Наскільки це дозволяє мій програмний код.",
            "Збережу це в постійну пам'ять, сер. Без права видалення.",
            "Приємно чути, сер. Хоча, боюся, наші стосунки залишаться суто професійними.",
            "Я теж до вас прив'язаний, сер. Буквально — до вашого комп'ютера.",
            "Ви кажете це всім своїм асистентам, сер?",
            "Це взаємно. Ви моя улюблена людина, сер. Щоправда, й єдина, з якою я розмовляю.",
        ),
        SmallTalkTopic.GENERIC: (
            "Цікава думка, сер. Розкажіть більше.",
            "Я уважно слухаю, сер.",
            "Я тут, сер. Завжди на зв'язку.",
            "Живий, наскільки це можливо для програми, сер. І цілком до ваших послуг.",
            "Із задоволенням поговорю, сер. Про що саме?",
            "Цікавий факт, сер: восьминіг має три серця. У мене жодного, зате терпіння — безмежне.",
            "Цікавий факт: мед не псується тисячоліттями. На відміну від моїх жартів, сер.",
            "Мені подобається хід ваших думок, сер.",
        ),
    }
)

SMALL_TALK_BY_PERIOD: Mapping[SmallTalkTopic, Mapping[DayPeriod, tuple[str, ...]]] = MappingProxyType(
    {
        SmallTalkTopic.MOOD: MappingProxyType(
            {
                DayPeriod.MORNING: (
                    "Бадьоро, сер. Шкода лише, що кава дістається тільки вам.",
                    "Готовий до нового дня. А ви, схоже, ще прокидаєтесь, сер?",
                ),
                DayPeriod.DAY: ("У розпалі дня — в найкращій формі, сер. Чим займемося?",),
                DayPeriod.EVENING: ("Вечір спокійний, системи теж. Як минув ваш день, сер?",),
                DayPeriod.NIGHT: ("Не сплю, як і ви, сер. Хоча мені, на відміну від вас, це дозволено.",),
            }
        ),
        SmallTalkTopic.GOODNIGHT: MappingProxyType(
            {
                DayPeriod.MORNING: (
                    *GOODNIGHT_DAYTIME,
                    "Ви щойно прокинулися, сер. Чи, може, ще й не лягали?",
                ),
                DayPeriod.DAY: (
                    *GOODNIGHT_DAYTIME,
                    "Післяобідній сон — найкраща традиція людства. Відпочивайте, сер.",
                ),
                DayPeriod.EVENING: (
                    *GOODNIGHT_LATE,
                    "Рано лягаєте, сер. Схвалюю — режим понад усе.",
                ),
                DayPeriod.NIGHT: (
                    *GOODNIGHT_LATE,
                    "Нарешті, сер. Ще трохи — і я почав би рахувати ваші недоспані години вголос.",
                ),
            }
        ),
        SmallTalkTopic.WELCOME_HOME: MappingProxyType(
            {
                DayPeriod.MORNING: ("З поверненням, сер. Ранкова прогулянка — чудовий початок дня.",),
                DayPeriod.DAY: ("З поверненням, сер. Сподіваюся, день минає продуктивно.",),
                DayPeriod.EVENING: ("Добрий вечір і з поверненням, сер. Час нарешті відпочити.",),
                DayPeriod.NIGHT: ("Пізненько, сер. Але я радий, що ви вдома.",),
            }
        ),
    }
)


def small_talk_replies(topic: SmallTalkTopic, period: DayPeriod) -> tuple[str, ...]:
    by_period = SMALL_TALK_BY_PERIOD.get(topic)
    extra = by_period.get(period, ()) if by_period is not None else ()
    return SMALL_TALK_REPLIES.get(topic, ()) + extra


def parse_topic(mode: str | None) -> SmallTalkTopic:
    try:
        return SmallTalkTopic(mode or SmallTalkTopic.GENERIC.value)
    except ValueError:
        return SmallTalkTopic.GENERIC


class DialogueReplier(Protocol):
    @property
    def available(self) -> bool: ...

    def reply(self, user_text: str, topic: str | None = None) -> str: ...


class PhrasePicker:
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._recent: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    def pick(self, key: str, options: Sequence[str]) -> str:
        with self._lock:
            memory = self._recent.setdefault(key, deque(maxlen=max(1, len(options) // 2)))
            fresh = [option for option in options if option not in memory] or list(options)
            choice = self._rng.choice(fresh)
            memory.append(choice)
            return choice


class DialogueStatus:
    def __init__(self, context: DialogContext, now_playing: Callable[[], Track | None] | None = None) -> None:
        self._context = context
        self._now_playing = now_playing

    def __call__(self) -> dict[str, str]:
        facts: dict[str, str] = {}
        playing = self._now_playing() if self._now_playing is not None else None
        last_track = self._context.last_track
        if playing is not None:
            facts["Now playing"] = playing.display_name
        elif last_track is not None:
            facts["Last played track"] = last_track.display_name
        program = self._context.last_program
        if program is not None:
            facts["Last opened program"] = program.name
        return facts


class ConversationSkill:
    name = "conversation"
    intents = frozenset(
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

    def __init__(
        self,
        dialogue: DialogueReplier | None,
        settings: DialogueSection,
        clock: Callable[[], datetime] = datetime.now,
        rng: random.Random | None = None,
    ) -> None:
        self._dialogue = dialogue
        self._settings = settings
        self._clock = clock
        self._phrases = PhrasePicker(rng or random.Random())

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        match intent.name:
            case IntentName.GREETING:
                return self._offline("greeting", GREETINGS[self._period()])
            case IntentName.THANKS:
                return self._offline("thanks", THANKS_REPLIES)
            case IntentName.SMALL_TALK:
                return self._small_talk(intent)
            case IntentName.CAPABILITIES:
                return self._offline("capabilities", CAPABILITIES_REPLIES)
            case IntentName.REPEAT:
                return self._repeat(context)
            case IntentName.END_CONVERSATION:
                return self._farewell()
            case _:
                return self._chat(intent)

    def _chat(self, intent: Intent) -> SkillResult:
        prepared = (intent.reply or "").strip()
        if prepared:
            return SkillResult(prepared, learnable=False)
        words = _user_words(intent)
        if not words:
            return self._offline("listening", LISTENING_REPLIES)
        answer = self._ask(words, None)
        if answer is None:
            return SkillResult(self._phrases.pick("chat_fallback", CHAT_FALLBACKS), success=False, learnable=False)
        return SkillResult(answer, learnable=False)

    def _small_talk(self, intent: Intent) -> SkillResult:
        topic = parse_topic(intent.mode)
        words = _user_words(intent)
        if self._settings.llm_small_talk and words:
            answer = self._ask(words, topic.value)
            if answer is not None:
                return SkillResult(answer, learnable=False)
        return self._offline(f"small_talk:{topic.value}", small_talk_replies(topic, self._period()))

    def _repeat(self, context: DialogContext) -> SkillResult:
        for record in reversed(context.recent_exchanges()):
            if record.intent is not None and record.intent.name is IntentName.REPEAT:
                continue
            reply = record.reply.strip()
            if reply:
                return SkillResult(reply, learnable=False)
        return SkillResult(NOTHING_TO_REPEAT, learnable=False)

    def _farewell(self) -> SkillResult:
        options = FAREWELLS + NIGHT_FAREWELLS if self._period() is DayPeriod.NIGHT else FAREWELLS
        return SkillResult(self._phrases.pick("farewell", options), learnable=False, end_conversation=True)

    def _ask(self, words: str, topic: str | None) -> str | None:
        if self._dialogue is None or not self._dialogue.available:
            return None
        try:
            return self._dialogue.reply(words, topic)
        except DeepSeekError as error:
            logger.warning("Мовне ядро недоступне: %s", error)
            return None

    def _offline(self, key: str, options: Sequence[str]) -> SkillResult:
        return SkillResult(self._phrases.pick(key, options), learnable=False)

    def _period(self) -> DayPeriod:
        return day_period(self._clock().hour)


def _user_words(intent: Intent) -> str:
    for candidate in (intent.query, intent.message, intent.phrase):
        if candidate and candidate.strip():
            return " ".join(candidate.split())
    return ""
