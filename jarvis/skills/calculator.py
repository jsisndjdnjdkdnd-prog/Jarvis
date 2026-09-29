from __future__ import annotations

import ast
import logging
import math
import operator
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.intent import Intent, IntentName
from jarvis.nlu.numbers import NumberWordsConverter

logger = logging.getLogger(__name__)

CANNOT_CALCULATE = "Не зміг порахувати, сер."
DIVISION_BY_ZERO = "На нуль ділити не можна, сер."

_CHARACTER_MAP = str.maketrans(
    {
        "’": "'", "ʼ": "'", "`": "'", "´": "'", "‘": "'", "ё": "е",
        "−": "-", "–": "-", "—": "-", "×": "*", "·": "*", "✕": "*", "÷": "/",
        "²": " ** 2 ", "³": " ** 3 ", "√": " sqrt ",
    }
)
_GROUPED_DIGITS = re.compile(r"\b\d{1,3}(?:[  ]\d{3})+\b")
_DECIMAL_SEPARATOR = re.compile(r"(?<=\d)[,.](?=\d)")
_TIMES_BETWEEN_DIGITS = re.compile(r"(?<=\d)\s*[xх]\s*(?=\d)")
_RATIO_BETWEEN_DIGITS = re.compile(r"(?<=\d)\s*:\s*(?=\d)")
_WORD_HYPHEN = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")
_SYMBOLS = re.compile(r"(\*\*|[-+*/^()%])")
_NOISE = re.compile(r"[^\w'.\s*/+\-^()%]")
_LOOSE_DOTS = re.compile(r"(?<!\d)\.|\.(?!\d)")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")

QUESTION_PREFIXES: tuple[tuple[str, ...], ...] = tuple(
    sorted(
        (
            tuple(prefix.split())
            for prefix in (
                "скільки буде", "скільки це буде", "скільки це", "скільки", "порахуй мені", "порахуй",
                "підрахуй", "обчисли", "вирахуй", "сколько будет", "сколько это", "сколько", "посчитай",
                "подсчитай", "вычисли", "what is", "what's", "how much is", "calculate", "compute",
            )
        ),
        key=len,
        reverse=True,
    )
)

WORD_REPLACEMENTS: dict[str, str] = {
    "півтора": "1.5", "півтори": "1.5", "полтора": "1.5", "полторы": "1.5",
    "нуля": "нуль", "однієї": "одна", "одного": "один",
    "п'яти": "п'ять", "шести": "шість", "семи": "сім", "восьми": "вісім", "дев'яти": "дев'ять",
    "десяти": "десять", "одинадцяти": "одинадцять", "дванадцяти": "дванадцять",
    "тринадцяти": "тринадцять", "чотирнадцяти": "чотирнадцять", "п'ятнадцяти": "п'ятнадцять",
    "шістнадцяти": "шістнадцять", "сімнадцяти": "сімнадцять", "вісімнадцяти": "вісімнадцять",
    "дев'ятнадцяти": "дев'ятнадцять", "двадцяти": "двадцять", "тридцяти": "тридцять", "сорока": "сорок",
    "п'ятдесяти": "п'ятдесят", "шістдесяти": "шістдесят", "сімдесяти": "сімдесят",
    "вісімдесяти": "вісімдесят", "дев'яноста": "дев'яносто",
    "пяти": "пять", "девяти": "девять", "одиннадцати": "одиннадцать", "двенадцати": "двенадцать",
    "двадцати": "двадцать", "тридцати": "тридцать", "пятидесяти": "пятьдесят",
    "шестидесяти": "шестьдесят", "семидесяти": "семьдесят", "восьмидесяти": "восемьдесят",
    "ста": "сто", "двохсот": "двісті", "трьохсот": "триста", "чотирьохсот": "чотириста",
    "п'ятисот": "п'ятсот", "двухсот": "двести", "трехсот": "триста", "четырехсот": "четыреста",
    "пятисот": "пятьсот",
    "шістсот": "шість сотня", "сімсот": "сім сотня", "вісімсот": "вісім сотня", "дев'ятсот": "дев'ять сотня",
    "шестисот": "шість сотня", "семисот": "сім сотня", "восьмисот": "вісім сотня",
    "дев'ятисот": "дев'ять сотня", "шестьсот": "шесть сотня", "семьсот": "семь сотня",
    "восемьсот": "восемь сотня", "девятьсот": "девять сотня",
    "hundred": "сотня", "hundreds": "сотня",
}

SCALE_WORDS: dict[str, int] = {
    **dict.fromkeys(("сотня", "сотні", "сотень", "сотню"), 100),
    **dict.fromkeys(
        ("тисяча", "тисячі", "тисяч", "тисячу", "тысяча", "тысячи", "тысяч", "тысячу", "thousand", "thousands"), 1000
    ),
    **dict.fromkeys(
        ("мільйон", "мільйона", "мільйони", "мільйонів", "миллион", "миллиона", "миллионов", "million", "millions"),
        1_000_000,
    ),
    **dict.fromkeys(
        ("мільярд", "мільярда", "мільярди", "мільярдів", "миллиард", "миллиарда", "миллиардов", "billion"),
        1_000_000_000,
    ),
}

DECIMAL_WORDS: frozenset[str] = frozenset(
    {"кома", "коми", "точка", "запятая", "point", "цілих", "ціла", "цілі", "целых", "целая"}
)
DENOMINATOR_WORDS: dict[str, int] = {
    **dict.fromkeys(("десятих", "десята", "десяті", "десятых", "десятая"), 10),
    **dict.fromkeys(("сотих", "сота", "соті", "сотых", "сотая"), 100),
    **dict.fromkeys(("тисячних", "тисячна", "тисячні", "тысячных", "тысячная"), 1000),
}


@dataclass(frozen=True)
class _Operator:
    symbol: str
    connector: str | None = None


def _operators(words: Sequence[str], symbol: str, connector: str | None) -> dict[str, _Operator]:
    return dict.fromkeys(words, _Operator(symbol, connector))


OPERATOR_WORDS: dict[str, _Operator] = {
    **_operators(("плюс", "plus", "+"), "+", None),
    **_operators(
        ("додати", "додай", "додаємо", "добавити", "добав", "прибавити", "прибав", "прибавить", "прибавь",
         "сложить", "сложи", "add"),
        "+",
        "+",
    ),
    **_operators(("мінус", "минус", "minus", "-"), "-", None),
    **_operators(
        ("відняти", "відніми", "віднімемо", "відняв", "отнять", "отними", "вычесть", "вычти", "subtract"), "-", "+"
    ),
    **_operators(("times", "*"), "*", None),
    **_operators(
        ("помножити", "помнож", "помножене", "помножена", "помножимо", "помножить", "множити", "множимо",
         "перемножити", "перемнож", "умножить", "умножь", "умножено", "multiply", "multiplied"),
        "*",
        "*",
    ),
    **_operators(("over", "/"), "/", None),
    **_operators(
        ("поділити", "поділи", "поділене", "поділена", "поділимо", "поділить", "ділити", "діли", "ділене",
         "розділити", "розділи", "поделить", "подели", "разделить", "раздели", "делить", "дели", "divide",
         "divided"),
        "/",
        "/",
    ),
    **_operators(
        ("степінь", "степені", "степеня", "ступінь", "ступені", "ступеня", "степень", "степени", "power", "^", "**"),
        "**",
        None,
    ),
}
UNARY_SYMBOLS: frozenset[str] = frozenset({"+", "-"})
SIGN_WORDS: frozenset[str] = frozenset(
    word for word, item in OPERATOR_WORDS.items() if item.symbol in UNARY_SYMBOLS and item.connector is None
)
POWER_WORDS: frozenset[str] = frozenset(word for word, item in OPERATOR_WORDS.items() if item.symbol == "**")

POSTFIX_WORDS: dict[str, str] = {
    **dict.fromkeys(("квадраті", "квадрате", "squared"), "**2"),
    **dict.fromkeys(("кубі", "кубе", "cubed"), "**3"),
}
ORDINAL_EXPONENTS: dict[str, int] = {
    **dict.fromkeys(("другому", "другій", "второй"), 2),
    **dict.fromkeys(("третьому", "третій", "третьей"), 3),
    **dict.fromkeys(("четвертому", "четвертій", "четвертой"), 4),
    **dict.fromkeys(("п'ятому", "п'ятій", "пятой"), 5),
    **dict.fromkeys(("шостому", "шостій", "шестой"), 6),
    **dict.fromkeys(("сьомому", "сьомій", "седьмой"), 7),
    **dict.fromkeys(("восьмому", "восьмій", "восьмой"), 8),
    **dict.fromkeys(("дев'ятому", "дев'ятій", "девятой"), 9),
    **dict.fromkeys(("десятому", "десятій", "десятой"), 10),
}
ROOT_WORDS: dict[str, str] = dict.fromkeys(("корінь", "корня", "кореня", "корень", "root", "sqrt"), "sqrt")
CUBE_ROOT_PHRASES: frozenset[tuple[str, str]] = frozenset(
    {
        ("кубічний", "корінь"), ("корінь", "кубічний"), ("кубический", "корень"), ("корень", "кубический"),
        ("cube", "root"),
    }
)
ROOT_TEMPLATES: dict[str, str] = {"sqrt": "sqrt({})", "cbrt": "({})**(1/3)"}
PERCENT_WORDS: frozenset[str] = frozenset(
    {"відсоток", "відсотки", "відсотків", "відсотка", "процент", "проценти", "процентів", "процента",
     "процентов", "percent", "percents", "%"}
)
OF_WORDS: frozenset[str] = frozenset({"від", "од", "от", "із", "з", "из", "of"})
CONNECTOR_WORDS: frozenset[str] = frozenset(
    {"на", "by", "до", "к", "to", "from", "і", "й", "та", "и", "and", "x", "х", *OF_WORDS}
)
MULTIPLYING_CONNECTORS: frozenset[str] = frozenset({"на", "by", "x", "х"})


def _is_number(token: str | None) -> bool:
    return token is not None and bool(_NUMBER.match(token))


def _render(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _normalize(text: str) -> list[str]:
    lowered = text.lower().translate(_CHARACTER_MAP)
    lowered = _GROUPED_DIGITS.sub(lambda match: re.sub(r"\D", "", match.group()), lowered)
    lowered = _DECIMAL_SEPARATOR.sub(".", lowered)
    lowered = _TIMES_BETWEEN_DIGITS.sub(" * ", lowered)
    lowered = _RATIO_BETWEEN_DIGITS.sub(" / ", lowered)
    lowered = _WORD_HYPHEN.sub(" ", lowered)
    lowered = _SYMBOLS.sub(r" \1 ", lowered)
    lowered = _NOISE.sub(" ", lowered)
    lowered = _LOOSE_DOTS.sub(" ", lowered)
    return [token.strip("'") for token in lowered.split() if token.strip("'")]


def _strip_question(words: list[str]) -> list[str]:
    for prefix in QUESTION_PREFIXES:
        if tuple(words[: len(prefix)]) == prefix:
            return words[len(prefix) :]
    return words


def _replace_words(words: list[str]) -> list[str]:
    return " ".join(WORD_REPLACEMENTS.get(word, word) for word in words).split()


class _NumberComposer:
    def __init__(self) -> None:
        self._output: list[str] = []
        self._reset()

    def _reset(self) -> None:
        self._started = False
        self._total = Decimal(0)
        self._group: Decimal | None = None
        self._open_below: Decimal | None = None
        self._last_big_scale: int | None = None

    def compose(self, tokens: Sequence[str]) -> list[str]:
        for token in tokens:
            self._feed(token)
        self._flush()
        return self._output

    def _feed(self, token: str) -> None:
        if _is_number(token):
            self._number(Decimal(token))
            return
        if token in SCALE_WORDS:
            self._scale(SCALE_WORDS[token])
            return
        self._flush()
        self._output.append(token)

    def _number(self, value: Decimal) -> None:
        if not self._accepts_number(value):
            self._flush()
        self._group = value if self._group is None else self._group + value
        self._open_below = None
        self._started = True

    def _accepts_number(self, value: Decimal) -> bool:
        if not self._started:
            return True
        return self._open_below is not None and value < self._open_below and value == value.to_integral_value()

    def _scale(self, scale: int) -> None:
        if not self._accepts_scale(scale):
            self._flush()
        if scale == 100:
            self._group = (self._group if self._group is not None else Decimal(1)) * scale
        else:
            self._total += (self._group if self._group is not None else Decimal(1)) * scale
            self._group = None
            self._last_big_scale = scale
        self._open_below = Decimal(scale)
        self._started = True

    def _accepts_scale(self, scale: int) -> bool:
        if not self._started:
            return True
        if self._group is None:
            return False
        if scale == 100:
            return self._group < 100 and self._open_below is None
        return self._last_big_scale is None or scale < self._last_big_scale

    def _flush(self) -> None:
        if self._started:
            self._output.append(_render(self._total + (self._group or Decimal(0))))
        self._reset()


def _join_decimals(tokens: Sequence[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(tokens):
        joined = _read_decimal(tokens, index)
        if joined is None:
            output.append(tokens[index])
            index += 1
            continue
        value, index = joined
        output.append(value)
    return output


def _read_decimal(tokens: Sequence[str], start: int) -> tuple[str, int] | None:
    if start + 2 >= len(tokens) or tokens[start + 1] not in DECIMAL_WORDS:
        return None
    whole = tokens[start]
    if not whole.isdigit() or not tokens[start + 2].isdigit():
        return None
    end = start + 2
    digits: list[str] = []
    while end < len(tokens) and tokens[end].isdigit():
        digits.append(tokens[end])
        end += 1
    if end < len(tokens) and tokens[end] in DENOMINATOR_WORDS and len(digits) == 1:
        fraction = Decimal(digits[0]) / DENOMINATOR_WORDS[tokens[end]]
        return _render(Decimal(whole) + fraction), end + 1
    return _render(Decimal(f"{whole}.{''.join(digits)}")), end


class _ExpressionAssembler:
    def __init__(self, tokens: Sequence[str]) -> None:
        self._tokens = tokens
        self._parts: list[str] = []
        self._expects_operand = True
        self._pending_connector: str | None = None
        self._pending_root: str | None = None

    def assemble(self) -> str:
        index = 0
        while index < len(self._tokens):
            index = self._consume(index)
        if self._expects_operand or self._pending_root is not None or not self._parts:
            raise ValueError("Вираз неповний")
        return "".join(self._parts)

    def _peek(self, index: int) -> str | None:
        return self._tokens[index] if index < len(self._tokens) else None

    def _consume(self, index: int) -> int:
        token = self._tokens[index]
        if _is_number(token):
            return self._number(index)
        if (token, self._peek(index + 1)) in CUBE_ROOT_PHRASES:
            self._root("cbrt")
            return index + 2
        if token in ORDINAL_EXPONENTS and self._peek(index + 1) in POWER_WORDS:
            self._postfix(f"**{ORDINAL_EXPONENTS[token]}")
            return index + 2
        self._word(token, self._peek(index + 1))
        return index + 1

    def _word(self, token: str, following: str | None) -> None:
        if token in OPERATOR_WORDS:
            self._operator(OPERATOR_WORDS[token])
        elif token in POSTFIX_WORDS:
            self._postfix(POSTFIX_WORDS[token])
        elif token in ROOT_WORDS:
            self._root(ROOT_WORDS[token])
        elif token in CONNECTOR_WORDS:
            self._connector(token, following)
        elif token == "(":
            self._open_parenthesis()
        elif token == ")":
            self._close_parenthesis()

    def _number(self, index: int) -> int:
        value = self._tokens[index]
        if self._peek(index + 1) not in PERCENT_WORDS:
            self._operand(value)
            return index + 1
        base = self._peek(index + 3)
        if self._peek(index + 2) in OF_WORDS and _is_number(base):
            self._operand(f"({value}/100*{base})")
            return index + 4
        self._operand(f"({value}/100)")
        return index + 2

    def _operand(self, text: str) -> None:
        if not self._expects_operand:
            raise ValueError("Два числа поспіль без дії")
        if self._pending_root is not None:
            text = ROOT_TEMPLATES[self._pending_root].format(text)
            self._pending_root = None
        self._parts.append(text)
        self._expects_operand = False

    def _operator(self, item: _Operator) -> None:
        if self._pending_root is not None:
            raise ValueError("Корінь без числа")
        if not self._expects_operand:
            self._parts.append(item.symbol)
            self._expects_operand = True
            return
        if item.symbol in UNARY_SYMBOLS:
            self._parts.append(item.symbol)
        if item.connector is not None:
            self._pending_connector = item.connector

    def _postfix(self, text: str) -> None:
        if self._expects_operand:
            raise ValueError("Степінь без основи")
        self._parts.append(text)

    def _root(self, kind: str) -> None:
        if not self._expects_operand or self._pending_root is not None:
            raise ValueError("Корінь у неочікуваному місці")
        self._pending_root = kind

    def _connector(self, word: str, following: str | None) -> None:
        if self._expects_operand or not self._starts_operand(following):
            return
        if self._pending_connector is not None:
            self._parts.append(self._pending_connector)
            self._pending_connector = None
        elif word in MULTIPLYING_CONNECTORS:
            self._parts.append("*")
        else:
            raise ValueError(f"Незрозумілий зв'язок «{word}»")
        self._expects_operand = True

    @staticmethod
    def _starts_operand(token: str | None) -> bool:
        if token is None:
            return False
        return _is_number(token) or token in ROOT_WORDS or token in SIGN_WORDS or token in {"(", "кубічний", "cube"}

    def _open_parenthesis(self) -> None:
        if not self._expects_operand or self._pending_root is not None:
            raise ValueError("Дужка у неочікуваному місці")
        self._parts.append("(")

    def _close_parenthesis(self) -> None:
        if self._expects_operand:
            raise ValueError("Порожні дужки")
        self._parts.append(")")


class ExpressionTranslator:
    def __init__(self, numbers: NumberWordsConverter | None = None) -> None:
        self._numbers = numbers or NumberWordsConverter()

    def translate(self, text: str) -> str:
        words = _replace_words(_strip_question(_normalize(text)))
        if not words:
            raise ValueError("Порожній вираз")
        converted = self._numbers.convert(" ".join(words)).split()
        tokens = _join_decimals(_NumberComposer().compose(converted))
        return _ExpressionAssembler(tokens).assemble()


_BINARY_OPERATIONS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPERATIONS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCTIONS: dict[str, Callable[[float], float]] = {"sqrt": math.sqrt}


class SafeCalculator:
    def __init__(self, max_exponent: float = 100.0, max_magnitude: float = 1e100, max_length: int = 300) -> None:
        self._max_exponent = max_exponent
        self._max_magnitude = max_magnitude
        self._max_length = max_length

    def evaluate(self, expression: str) -> float:
        if not expression.strip() or len(expression) > self._max_length:
            raise ValueError("Вираз порожній або задовгий")
        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except SyntaxError as error:
            raise ValueError(f"Некоректний вираз: {expression}") from error
        return self._evaluate(tree)

    def _evaluate(self, node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return self._evaluate(node.body)
        if isinstance(node, ast.Constant):
            return self._constant(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATIONS:
            return self._checked(_UNARY_OPERATIONS[type(node.op)](self._evaluate(node.operand)))
        if isinstance(node, ast.BinOp):
            return self._binary(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ValueError(f"Недозволений елемент виразу: {type(node).__name__}")

    @staticmethod
    def _constant(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Дозволені лише числа")
        return float(value)

    def _binary(self, node: ast.BinOp) -> float:
        left = self._evaluate(node.left)
        right = self._evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            return self._power(left, right)
        operation = _BINARY_OPERATIONS.get(type(node.op))
        if operation is None:
            raise ValueError(f"Недозволена операція: {type(node.op).__name__}")
        try:
            return self._checked(operation(left, right))
        except OverflowError as error:
            raise ValueError("Занадто велике число") from error

    def _power(self, base: float, exponent: float) -> float:
        if abs(exponent) > self._max_exponent:
            raise ValueError("Занадто великий степінь")
        try:
            result: object = base**exponent
        except OverflowError as error:
            raise ValueError("Занадто велике число") from error
        if not isinstance(result, float | int):
            raise ValueError("Результат не є дійсним числом")
        return self._checked(float(result))

    def _call(self, node: ast.Call) -> float:
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("Недозволена функція")
        if len(node.args) != 1 or node.keywords:
            raise ValueError("Функція приймає рівно один аргумент")
        return self._checked(_FUNCTIONS[node.func.id](self._evaluate(node.args[0])))

    def _checked(self, value: float) -> float:
        if not math.isfinite(value) or abs(value) > self._max_magnitude:
            raise ValueError("Результат поза допустимими межами")
        return value


def format_number(value: float) -> str:
    if value < 0:
        return f"мінус {format_number(-value)}"
    if value == 0:
        return "0"
    if value >= 1e15:
        return _scientific(value)
    decimals = 4 if value >= 1 else min(12, 3 - math.floor(math.log10(value)))
    rounded = round(value, decimals)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".").replace(".", ",")


def _scientific(value: float) -> str:
    mantissa, exponent = f"{value:.3e}".split("e")
    spoken_mantissa = mantissa.rstrip("0").rstrip(".").replace(".", ",")
    return f"{spoken_mantissa} на десять у степені {int(exponent)}"


class CalculatorSkill:
    name = "calculator"
    intents = frozenset({IntentName.CALCULATE})

    def __init__(self, translator: ExpressionTranslator, calculator: SafeCalculator) -> None:
        self._translator = translator
        self._calculator = calculator

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        text = intent.query or intent.target or intent.phrase or ""
        try:
            expression = self._translator.translate(text)
            value = self._calculator.evaluate(expression)
        except ZeroDivisionError:
            return SkillResult(DIVISION_BY_ZERO, success=False, learnable=False)
        except ValueError as error:
            logger.info("Не вдалося порахувати «%s»: %s", text, error)
            return SkillResult(CANNOT_CALCULATE, success=False, learnable=False)
        logger.debug("Обчислено %s = %s", expression, value)
        return SkillResult(f"Це буде {format_number(value)}.", learnable=False)
