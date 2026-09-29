from __future__ import annotations

UNITS: dict[str, int] = {
    "нуль": 0, "ноль": 0, "zero": 0,
    "один": 1, "одна": 1, "одну": 1, "одне": 1, "одно": 1, "одного": 1, "одной": 1, "one": 1,
    "два": 2, "дві": 2, "две": 2, "двох": 2, "two": 2,
    "три": 3, "трьох": 3, "трех": 3, "three": 3,
    "чотири": 4, "четыре": 4, "чотирьох": 4, "four": 4,
    "п'ять": 5, "пять": 5, "five": 5,
    "шість": 6, "шесть": 6, "six": 6,
    "сім": 7, "семь": 7, "seven": 7,
    "вісім": 8, "восемь": 8, "eight": 8,
    "дев'ять": 9, "девять": 9, "nine": 9,
}

TEENS: dict[str, int] = {
    "десять": 10, "ten": 10,
    "одинадцять": 11, "одиннадцать": 11, "eleven": 11,
    "дванадцять": 12, "двенадцать": 12, "twelve": 12,
    "тринадцять": 13, "тринадцать": 13, "thirteen": 13,
    "чотирнадцять": 14, "четырнадцать": 14, "fourteen": 14,
    "п'ятнадцять": 15, "пятнадцать": 15, "fifteen": 15,
    "шістнадцять": 16, "шестнадцать": 16, "sixteen": 16,
    "сімнадцять": 17, "семнадцать": 17, "seventeen": 17,
    "вісімнадцять": 18, "восемнадцать": 18, "eighteen": 18,
    "дев'ятнадцять": 19, "девятнадцать": 19, "nineteen": 19,
}

TENS: dict[str, int] = {
    "двадцять": 20, "двадцать": 20, "twenty": 20,
    "тридцять": 30, "тридцать": 30, "thirty": 30,
    "сорок": 40, "forty": 40,
    "п'ятдесят": 50, "пятьдесят": 50, "fifty": 50,
    "шістдесят": 60, "шестьдесят": 60, "sixty": 60,
    "сімдесят": 70, "семьдесят": 70, "seventy": 70,
    "вісімдесят": 80, "восемьдесят": 80, "eighty": 80,
    "дев'яносто": 90, "девяносто": 90, "ninety": 90,
}

HUNDREDS: dict[str, int] = {
    "сто": 100, "hundred": 100,
    "двісті": 200, "двести": 200,
    "триста": 300,
    "чотириста": 400, "четыреста": 400,
    "п'ятсот": 500, "пятьсот": 500,
}

HOUR_ORDINALS: dict[str, int] = {
    "першій": 1, "первом": 1, "час": 1,
    "другій": 2, "втором": 2,
    "третій": 3, "третьем": 3,
    "четвертій": 4, "четвертом": 4,
    "п'ятій": 5, "пятом": 5,
    "шостій": 6, "шестом": 6,
    "сьомій": 7, "седьмом": 7,
    "восьмій": 8, "восьмом": 8,
    "дев'ятій": 9, "девятом": 9,
    "десятій": 10, "десятом": 10,
    "одинадцятій": 11, "одиннадцатом": 11,
    "дванадцятій": 12, "двенадцатом": 12,
}

def word_to_number(word: str) -> int | None:
    for table in (UNITS, TEENS, TENS, HUNDREDS):
        if word in table:
            return table[word]
    return None


class NumberWordsConverter:
    def convert(self, text: str) -> str:
        tokens = text.split()
        output: list[str] = []
        index = 0
        while index < len(tokens):
            value, consumed = self._read_number(tokens, index)
            if consumed == 0:
                output.append(tokens[index])
                index += 1
                continue
            output.append(str(value))
            index += consumed
        return " ".join(output)

    def _read_number(self, tokens: list[str], start: int) -> tuple[int, int]:
        total = 0
        index = start
        last_magnitude = 1000
        while index < len(tokens):
            magnitude, value = self._classify(tokens[index])
            if magnitude is None or magnitude >= last_magnitude:
                break
            total += value
            last_magnitude = magnitude
            index += 1
        return total, index - start

    @staticmethod
    def _classify(token: str) -> tuple[int | None, int]:
        if token in HUNDREDS:
            return 100, HUNDREDS[token]
        if token in TENS:
            return 10, TENS[token]
        if token in TEENS:
            return 1, TEENS[token]
        if token in UNITS:
            return 1, UNITS[token]
        return None, 0
