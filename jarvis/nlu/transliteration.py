from __future__ import annotations

import re

_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "yu",
    "я": "ya", "ё": "yo", "ы": "y", "э": "e", "ъ": "", "'": "",
}

_LATIN_DIGRAPHS: tuple[tuple[str, str], ...] = (
    ("shch", "щ"), ("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"),
    ("ts", "ц"), ("ya", "я"), ("yu", "ю"), ("ye", "є"), ("yi", "ї"), ("oo", "у"),
    ("ee", "і"), ("ph", "ф"), ("th", "т"), ("ck", "к"), ("qu", "кв"), ("wh", "в"),
    ("ou", "ау"), ("ai", "ей"), ("ay", "ей"), ("ea", "і"),
)

_LATIN_LETTERS: dict[str, str] = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "і", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "і", "z": "з",
}

_PHONETIC_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("shch", "sh"), ("chr", "hr"), ("kh", "h"), ("ph", "f"), ("th", "t"), ("ck", "k"), ("qu", "kv"),
    ("wh", "v"), ("ee", "i"), ("oo", "u"), ("ou", "au"), ("ea", "i"), ("x", "ks"),
    ("w", "v"), ("q", "k"), ("c", "k"), ("j", "dzh"), ("yi", "i"), ("ye", "e"),
    ("y", "i"), ("g", "h"),
)

_REPEATED = re.compile(r"(.)\1+")
_CYRILLIC = re.compile(r"[а-яіїєґёыэъ]")


def contains_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text.lower()))


def cyrillic_to_latin(text: str) -> str:
    return "".join(_CYRILLIC_TO_LATIN.get(char, char) for char in text.lower())


def latin_to_cyrillic(text: str) -> str:
    lowered = text.lower()
    result: list[str] = []
    index = 0
    while index < len(lowered):
        matched = _match_digraph(lowered, index)
        if matched is not None:
            source, target = matched
            result.append(target)
            index += len(source)
            continue
        char = lowered[index]
        result.append(_LATIN_LETTERS.get(char, char))
        index += 1
    return "".join(result)


def _match_digraph(text: str, index: int) -> tuple[str, str] | None:
    for source, target in _LATIN_DIGRAPHS:
        if text.startswith(source, index):
            return source, target
    return None


def phonetic_key(text: str) -> str:
    latin = cyrillic_to_latin(text)
    for source, target in _PHONETIC_REPLACEMENTS:
        latin = latin.replace(source, target)
    latin = re.sub(r"e\b", "", latin)
    latin = _REPEATED.sub(r"\1", latin)
    return re.sub(r"\s+", " ", latin).strip()
