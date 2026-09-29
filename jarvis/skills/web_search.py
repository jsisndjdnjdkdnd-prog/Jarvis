from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import quote_plus

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ActionExecutionError
from jarvis.core.intent import Intent, IntentName

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_URL = "https://www.google.com/search?q="


class UrlOpener(Protocol):
    def open(self, target: str) -> None: ...


class WebSearchSkill:
    name = "web_search"
    intents = frozenset({IntentName.WEB_SEARCH})

    def __init__(self, opener: UrlOpener) -> None:
        self._opener = opener

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        query = " ".join((intent.query or intent.target or "").split())
        if not query:
            return SkillResult("Що саме знайти, сер?", success=False, learnable=False)
        try:
            self._opener.open(f"{GOOGLE_SEARCH_URL}{quote_plus(query)}")
        except ActionExecutionError as error:
            logger.warning("Не вдалося відкрити пошук: %s", error)
            return SkillResult("Не вдалося відкрити браузер, сер.", success=False, learnable=False)
        return SkillResult(f"Шукаю «{query}» в Google.", learnable=False)
