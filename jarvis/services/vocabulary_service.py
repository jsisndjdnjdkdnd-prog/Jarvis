from __future__ import annotations

import logging
import shutil
from pathlib import Path

from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    VocabularyChanged,
    VocabularyListed,
    VocabularyListRequested,
    VocabularyWordDeleteRequested,
)
from jarvis.storage.repositories.vocabulary import VocabularyRepository

logger = logging.getLogger(__name__)


class VocabularyService:
    def __init__(self, bus: EventBus, repository: VocabularyRepository, voice_dir: Path) -> None:
        self._bus = bus
        self._repository = repository
        self._voice_dir = voice_dir

    def start(self) -> None:
        self._bus.subscribe(VocabularyListRequested, lambda _: self._publish_list())
        self._bus.subscribe(VocabularyWordDeleteRequested, self._delete)

    def _publish_list(self) -> None:
        self._bus.publish(VocabularyListed(tuple(self._repository.list_words())))

    def _delete(self, event: VocabularyWordDeleteRequested) -> None:
        if not self._repository.delete_word(event.word_id):
            return
        shutil.rmtree(self._voice_dir / str(event.word_id), ignore_errors=True)
        logger.info("Слово %d видалено", event.word_id)
        self._bus.publish(VocabularyChanged())
