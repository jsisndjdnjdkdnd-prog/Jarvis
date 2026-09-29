from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from jarvis.core.intent import Action, ActionType, Intent, IntentName
from jarvis.core.models import (
    AliasSource,
    Binding,
    BindingSource,
    PreferenceKind,
    Program,
    ProgramKind,
    ReminderStatus,
)
from jarvis.storage.db import Database
from jarvis.storage.migrations import MIGRATIONS, Migrator
from jarvis.storage.repositories import Repositories


def test_migrations_set_user_version(database: Database) -> None:
    assert Migrator(database).current_version() == MIGRATIONS[-1].version
    assert Migrator(database).migrate() == MIGRATIONS[-1].version


def test_binding_roundtrip_with_macro(repositories: Repositories) -> None:
    macro = Action(
        type=ActionType.MACRO,
        steps=(Action(type=ActionType.OPEN_APP, target="Discord"), Action(type=ActionType.LAUNCH, target="steam://rungameid/570")),
    )
    saved = repositories.bindings.save(Binding(None, "Бойовий режим", "бойовий режим", macro))
    loaded = repositories.bindings.find_by_normalized("бойовий режим")
    assert loaded is not None
    assert loaded.id == saved.id
    assert loaded.action == macro
    assert loaded.source is BindingSource.USER


def test_binding_upsert_by_phrase(repositories: Repositories) -> None:
    first = repositories.bindings.save(Binding(None, "дотка", "дотка", Action(type=ActionType.OPEN_APP, target="dota")))
    second = repositories.bindings.save(
        Binding(None, "дотка", "дотка", Action(type=ActionType.LAUNCH, target="steam://rungameid/570"))
    )
    assert first.id == second.id
    assert len(repositories.bindings.list_all()) == 1
    assert repositories.bindings.list_all()[0].action.type is ActionType.LAUNCH


def test_binding_with_intent_action(repositories: Repositories) -> None:
    action = Action(type=ActionType.INTENT, intent=Intent(name=IntentName.SCREENSHOT, mode="window"))
    repositories.bindings.save(Binding(None, "фото вікна", "фото вікна", action, BindingSource.LEARNED))
    loaded = repositories.bindings.find_by_normalized("фото вікна")
    assert loaded is not None
    assert loaded.action.intent is not None
    assert loaded.action.intent.mode == "window"
    assert repositories.bindings.count_by_source(BindingSource.LEARNED) == 1


def test_binding_usage_counter_and_delete(repositories: Repositories) -> None:
    binding = repositories.bindings.save(Binding(None, "x", "x", Action(type=ActionType.SHELL, target="echo")))
    assert binding.id is not None
    repositories.bindings.mark_used(binding.id)
    repositories.bindings.mark_used(binding.id)
    assert repositories.bindings.get(binding.id).use_count == 2
    assert repositories.bindings.delete(binding.id)
    assert repositories.bindings.get(binding.id) is None


def test_vocabulary_aliases_weights(repositories: Repositories, tmp_path: Path) -> None:
    word = repositories.vocabulary.add_word("Malwarebytes", "malwarebytes", None)
    assert word.id is not None
    alias = repositories.vocabulary.upsert_alias(word.id, "мал вер байтс", "мал вер байтс", AliasSource.TRAINING)
    duplicate = repositories.vocabulary.upsert_alias(word.id, "мал вер байтс", "мал вер байтс", AliasSource.USAGE)
    assert alias.id == duplicate.id
    repositories.vocabulary.penalize_alias(alias.id, penalty=0.25, min_weight=0.3)
    assert repositories.vocabulary.list_aliases(word.id)[0].weight == 0.75
    repositories.vocabulary.reinforce_alias(alias.id, reward=0.5)
    assert repositories.vocabulary.list_aliases(word.id)[0].weight == 1.0
    for _ in range(3):
        repositories.vocabulary.penalize_alias(alias.id, penalty=0.25, min_weight=0.3)
    assert repositories.vocabulary.list_aliases(word.id) == []


def test_vocabulary_samples_cascade(repositories: Repositories, tmp_path: Path) -> None:
    word = repositories.vocabulary.add_word("Dota", "dota", Action(type=ActionType.OPEN_APP, target="dota 2"))
    sample = repositories.vocabulary.add_sample(word.id, tmp_path / "a.wav", 0.8, ("дота", "до та"), b"features")
    assert sample.transcripts == ("дота", "до та")
    reloaded = repositories.vocabulary.get_word(word.id)
    assert reloaded.sample_count == 1
    assert reloaded.action.target == "dota 2"
    repositories.vocabulary.delete_word(word.id)
    assert repositories.vocabulary.list_samples(word.id) == []


def test_programs_replace_index_keeps_user_programs(repositories: Repositories) -> None:
    user = Program(None, "My Tool", "my tool", "C:/tool.exe", ProgramKind.USER, "user", ("tool.exe",), is_user_defined=True)
    repositories.programs.save(user, {"мій тул": "мій тул"})
    indexed = Program(None, "Google Chrome", "google chrome", "chrome.lnk", ProgramKind.SHORTCUT, "start_menu", ("chrome.exe",))
    count = repositories.programs.replace_indexed([(indexed, {"хром": "хром", "google chrome": "google chrome"})])
    assert count == 1
    programs = {program.name: program for program in repositories.programs.list_all()}
    assert set(programs) == {"My Tool", "Google Chrome"}
    assert "хром" in programs["Google Chrome"].aliases
    assert programs["Google Chrome"].process_names == ("chrome.exe",)
    repositories.programs.replace_indexed([])
    assert [program.name for program in repositories.programs.list_all()] == ["My Tool"]


def test_reminders_due_and_status(repositories: Repositories, now: datetime) -> None:
    past = repositories.reminders.add("подзвонити мамі", now - timedelta(minutes=1))
    repositories.reminders.add("зустріч", now + timedelta(hours=1))
    due = repositories.reminders.due(now)
    assert [item.message for item in due] == ["подзвонити мамі"]
    repositories.reminders.set_status(past.id, ReminderStatus.DONE)
    assert repositories.reminders.due(now) == []
    assert len(repositories.reminders.pending()) == 1


def test_deepseek_cache_and_stats(repositories: Repositories) -> None:
    repositories.deepseek_cache.put("яка погода", '{"name": "chat"}')
    assert repositories.deepseek_cache.get("яка погода") == '{"name": "chat"}'
    assert repositories.deepseek_cache.get("інше") is None
    repositories.deepseek_stats.record_call("intent", True, 120.0, 100, 20)
    repositories.deepseek_stats.record_call("music", False, 80.0, 0, 0)
    stats = repositories.deepseek_stats.snapshot(cache_hits=repositories.deepseek_cache.total_hits(), learned_phrases=3)
    assert stats.total_calls == 2
    assert stats.successful_calls == 1
    assert stats.failed_calls == 1
    assert stats.cache_hits == 1
    assert stats.prompt_tokens == 100
    assert stats.by_purpose == {"intent": 1, "music": 1}


def test_preferences_and_history(repositories: Repositories) -> None:
    repositories.preferences.bump(PreferenceKind.ARTIST, "Imagine Dragons", 2)
    repositories.preferences.bump(PreferenceKind.ARTIST, "imagine dragons", 1)
    repositories.preferences.bump(PreferenceKind.ARTIST, "Muse", 1)
    top = repositories.preferences.top(PreferenceKind.ARTIST)
    assert top[0].value == "Imagine Dragons"
    assert top[0].weight == 3
    repositories.listening.record("Muse", "Uprising", "https://soundcloud.com/muse/uprising")
    repositories.listening.mark_liked("https://soundcloud.com/muse/uprising")
    assert repositories.listening.recent(5)[0].liked


def test_command_history(repositories: Repositories) -> None:
    repositories.history.record("відкрий хром", "відкрий хром", '{"name": "open_app"}', "rules", True, "Відкриваю")
    repositories.history.record("щось", "щось", None, None, False, "Не зрозумів")
    assert len(repositories.history.recent()) == 2
    assert repositories.history.most_used_intents() == [("open_app", 1)]
