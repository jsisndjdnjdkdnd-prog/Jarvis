from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.core.assistant import Assistant
from jarvis.core.config import AppConfig, ConfigRepository, read_deepseek_api_key
from jarvis.core.context import DialogContext
from jarvis.core.errors import AudioDeviceError, JarvisError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import ErrorOccurred, ProgramsIndexed, ShutdownRequested, SpeakRequested
from jarvis.core.logging_setup import configure_logging
from jarvis.core.paths import AppPaths
from jarvis.core.scheduler import Scheduler
from jarvis.nlu.deepseek_client import DeepSeekClient
from jarvis.nlu.deepseek_intents import DeepSeekIntentResolver
from jarvis.nlu.dialogue import DialogueEngine
from jarvis.nlu.fuzzy_matcher import FuzzyMatcher, PhraseSimilarity
from jarvis.nlu.intent_actions import IntentActionMapper
from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.interpreter import NluInterpreter
from jarvis.nlu.phrase_learner import AliasFeedback, PhraseLearner
from jarvis.nlu.pipeline import (
    BindingCatalog,
    DeepSeekCacheStage,
    DeepSeekStage,
    ExactBindingStage,
    FuzzyBindingStage,
    IntentPipeline,
    RuleStage,
)
from jarvis.nlu.pronunciation_matcher import PronunciationMatcher, PronunciationScorer, VocabularyIndex
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.time_parser import NaturalTimeParser
from jarvis.services.bindings_service import BindingsService
from jarvis.services.catalog_refresher import CatalogRefresher
from jarvis.services.notifications import ToastNotifier
from jarvis.services.programs_service import ProgramsService
from jarvis.services.reminders_service import RemindersUiService
from jarvis.services.settings_service import SettingsService
from jarvis.services.stats_service import DeepSeekStatsService
from jarvis.services.vocabulary_service import VocabularyService
from jarvis.skills.actions import ActionExecutor, HotkeySender
from jarvis.skills.apps.catalog import ProgramAliasBuilder, ProgramCatalog
from jarvis.skills.apps.indexer import ProgramIndexer
from jarvis.skills.apps.launcher import FolderResolver, ProcessCloser, ProgramLauncher, UrlResolver
from jarvis.skills.apps.skill import AppsSkill, ProgramService
from jarvis.skills.apps.sources import (
    AppPathsSource,
    EpicGamesSource,
    ProgramFilesSource,
    ProgramSource,
    RegistryReader,
    ShortcutResolver,
    StartMenuSource,
    SteamSource,
    SystemProgramsSource,
    UninstallSource,
    UwpAppsSource,
)
from jarvis.skills.base import SkillDispatcher, SkillRegistry
from jarvis.skills.bindings import BindingsSkill
from jarvis.skills.calculator import CalculatorSkill, ExpressionTranslator, SafeCalculator
from jarvis.skills.conversation import ConversationSkill
from jarvis.skills.input_control import WindowsInputController
from jarvis.skills.media_soundcloud.player import BrowserPlayer, MusicPlayer, VlcPlayer
from jarvis.skills.media_soundcloud.recommender import (
    DeepSeekMusicRecommender,
    FallbackMusicRecommender,
    LocalMusicRecommender,
)
from jarvis.skills.media_soundcloud.search import (
    FallbackTrackSearch,
    SoundCloudApiSearch,
    TrackRanker,
    TrackSearch,
    YtDlpClient,
    YtDlpSoundCloudSearch,
    YtDlpStreamResolver,
)
from jarvis.skills.media_soundcloud.skill import MusicService, MusicSkill
from jarvis.skills.plan import PlanSkill
from jarvis.skills.platform import ShellOpener, is_windows
from jarvis.skills.reminders import ReminderService, RemindersSkill
from jarvis.skills.screenshots import (
    RegionSelector,
    ScreenGrabber,
    ScreenshotService,
    ScreenshotsSkill,
    Win32ActiveWindowLocator,
    Win32ClipboardWriter,
)
from jarvis.skills.system import PycawVolumeController, SystemSkill, WindowsPowerController
from jarvis.skills.system_extras import SystemExtrasSkill, WindowsPowerExtras
from jarvis.skills.system_info import PsutilProbe, SystemInfoSkill
from jarvis.skills.timers import TimerService, TimersSkill
from jarvis.skills.weather import OpenMeteoClient, WeatherSkill
from jarvis.skills.web_search import WebSearchSkill
from jarvis.skills.window_control import WindowControlSkill
from jarvis.skills.window_manager import Win32WindowManager
from jarvis.skills.youtube import YouTubePlaySkill, YtDlpYouTubeSearch
from jarvis.skills.youtube_control import YouTubeControlSkill
from jarvis.speech.audio_io import AudioPlayer, MicrophoneStream, UtteranceRecorder
from jarvis.speech.audio_preprocess import AudioPreprocessor
from jarvis.speech.grammar import GrammarProvider, command_keywords
from jarvis.speech.listener import VoiceListener
from jarvis.speech.recognizer_vosk import (
    SpeechTranscriber,
    StreamingRecognizer,
    VoskModelProvider,
    VoskRecognizerFactory,
    VoskResultParser,
)
from jarvis.speech.transcriber import Transcriber
from jarvis.speech.tts import EdgeTtsSpeaker, FallbackSpeaker, Pyttsx3Speaker, SpeechService
from jarvis.speech.wake_word import WakeWordDetector, WakeWordMatcher
from jarvis.speech.whisper_engine import WhisperModelProvider, WhisperTranscriber
from jarvis.storage.db import Database
from jarvis.storage.migrations import Migrator
from jarvis.storage.repositories import Repositories
from jarvis.training.pronunciation_trainer import PronunciationTrainer, SampleTranscriber
from jarvis.training.voice_templates import AcousticModelBuilder, DtwComparer, MfccExtractor, ThresholdEstimator
from jarvis.ui.app import DesktopUi

logger = logging.getLogger(__name__)

STARTUP_GREETING = "Системи онлайн. До ваших послуг, сер."


class Startable(Protocol):
    def start(self) -> None: ...


@dataclass(frozen=True)
class NluBundle:
    normalizer: TextNormalizer
    matcher: FuzzyMatcher
    scorer: PronunciationScorer
    vocabulary_index: VocabularyIndex
    binding_catalog: BindingCatalog
    program_catalog: ProgramCatalog
    interpreter: NluInterpreter
    deepseek: DeepSeekClient
    extractor: MfccExtractor
    builder: AcousticModelBuilder


@dataclass(frozen=True)
class SpeechBundle:
    microphone: MicrophoneStream
    models: VoskModelProvider
    transcriber: SpeechTranscriber
    command_transcriber: Transcriber
    whisper_provider: WhisperModelProvider | None
    grammar: GrammarProvider
    wake_matcher: WakeWordMatcher
    listener: VoiceListener
    speech_service: SpeechService


@dataclass(frozen=True)
class SkillBundle:
    dispatcher: SkillDispatcher
    indexer: ProgramIndexer
    program_launcher: ProgramLauncher
    alias_builder: ProgramAliasBuilder
    reminders: ReminderService


class Application:
    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        database: Database,
        scheduler: Scheduler,
        speech: SpeechBundle,
        skills: SkillBundle,
        startables: Sequence[Startable],
        refresher: CatalogRefresher,
        ui: DesktopUi,
    ) -> None:
        self._config = config
        self._bus = bus
        self._database = database
        self._scheduler = scheduler
        self._speech = speech
        self._skills = skills
        self._startables = tuple(startables)
        self._refresher = refresher
        self._ui = ui

    def run(self) -> None:
        self._bus.start()
        self._scheduler.start()
        self._refresher.refresh_all()
        for component in self._startables:
            component.start()
        self._skills.reminders.start()
        self._schedule_indexing()
        self._preload_whisper()
        self._start_voice()
        self._bus.publish(SpeakRequested(STARTUP_GREETING))
        try:
            self._ui.run()
        finally:
            self._shutdown()

    def _schedule_indexing(self) -> None:
        settings = self._config.programs
        if settings.reindex_on_start and self._skills.indexer.needs_rescan(settings.reindex_max_age_hours):
            self._skills.indexer.rescan_async()

    def _preload_whisper(self) -> None:
        provider = self._speech.whisper_provider
        if provider is not None and self._config.speech.whisper.preload:
            provider.preload_async()

    def _start_voice(self) -> None:
        primary = self._config.speech.primary_language
        if primary not in self._speech.models.languages:
            path = self._config.speech.models.get(primary)
            self._bus.publish(
                ErrorOccurred(f"Модель Vosk «{primary}» не знайдена ({path}). Працюю в текстовому режимі.")
            )
            return
        try:
            self._speech.microphone.start()
        except AudioDeviceError as error:
            self._bus.publish(ErrorOccurred(f"{error}. Працюю в текстовому режимі."))
            return
        self._speech.listener.start()

    def _shutdown(self) -> None:
        logger.info("Зупинка J.A.R.V.I.S.")
        self._bus.dispatch_now(ShutdownRequested())
        self._speech.listener.stop()
        self._speech.microphone.stop()
        self._scheduler.stop()
        self._bus.stop()
        self._database.close()


def build_application(paths: AppPaths) -> Application:
    config_repository = ConfigRepository(paths)
    config = config_repository.load()
    configure_logging(config.app.log_level, paths.resolve(config.app.log_file))
    database = Database(paths.resolve(config.storage.database))
    Migrator(database).migrate()
    repositories = Repositories.create(database)
    bus = EventBus()
    scheduler = Scheduler()
    context = DialogContext(conversation_mode=config.speech.wake.conversation_mode)
    stats_service = DeepSeekStatsService(
        bus, repositories.deepseek_stats, repositories.deepseek_cache, repositories.bindings, repositories.history
    )
    nlu = _build_nlu(config, repositories, bus, stats_service.publish, context)
    skills = _build_skills(config, paths, repositories, bus, scheduler, nlu, context)
    speech = _build_speech(config, paths, bus, nlu)
    assistant = Assistant(bus, nlu.interpreter, skills.dispatcher, repositories.history, context)
    trainer = _build_trainer(config, paths, bus, repositories, speech, nlu)
    refresher = CatalogRefresher(
        bus, nlu.binding_catalog, nlu.vocabulary_index, nlu.program_catalog, speech.grammar, speech.wake_matcher
    )
    startables: list[Startable] = [
        refresher,
        stats_service,
        BindingsService(bus, repositories.bindings, nlu.normalizer),
        VocabularyService(bus, repositories.vocabulary, paths.resolve(config.training.voice_dir)),
        ProgramsService(
            bus, repositories.programs, nlu.program_catalog, skills.indexer, skills.program_launcher, skills.alias_builder
        ),
        RemindersUiService(bus, skills.reminders),
        SettingsService(bus, config_repository),
        ToastNotifier(bus),
        assistant,
        speech.speech_service,
        trainer,
    ]
    ui = DesktopUi(bus, config, paths.resolve(config.app.data_dir) / "webview")
    return Application(config, bus, database, scheduler, speech, skills, startables, refresher, ui)


def _build_nlu(
    config: AppConfig,
    repositories: Repositories,
    bus: EventBus,
    on_deepseek_call: Callable[[], None],
    context: DialogContext,
) -> NluBundle:
    normalizer = TextNormalizer(wake_words=config.speech.wake.words)
    similarity = PhraseSimilarity()
    matcher = FuzzyMatcher(similarity)
    extractor = MfccExtractor(config.training.mfcc_features)
    comparer = DtwComparer()
    builder = AcousticModelBuilder(
        comparer, ThresholdEstimator(config.training.threshold_std_factor, config.training.threshold_min_margin)
    )
    scorer = PronunciationScorer(similarity, extractor, comparer, config.nlu)
    vocabulary_index = VocabularyIndex(repositories.vocabulary)
    binding_catalog = BindingCatalog(repositories.bindings)
    program_catalog = ProgramCatalog(repositories.programs, matcher, config.nlu)
    parser = IntentParser(NaturalTimeParser(default_hour=config.reminders.default_hour), program_catalog)
    deepseek = DeepSeekClient(config.deepseek, read_deepseek_api_key(), repositories.deepseek_stats, on_deepseek_call)
    if not deepseek.available:
        logger.warning("DeepSeek вимкнено: немає DEEPSEEK_API_KEY або deepseek.enabled = false")
    pipeline = IntentPipeline(
        (
            ExactBindingStage(binding_catalog),
            FuzzyBindingStage(binding_catalog, matcher, config.nlu),
            RuleStage(parser),
            DeepSeekCacheStage(repositories.deepseek_cache),
            DeepSeekStage(
                DeepSeekIntentResolver(deepseek, history=context.recent_exchanges), repositories.deepseek_cache
            ),
        )
    )
    interpreter = NluInterpreter(
        normalizer,
        PronunciationMatcher(vocabulary_index, scorer, normalizer, config.nlu),
        pipeline,
        PhraseLearner(repositories.bindings, IntentActionMapper()),
        AliasFeedback(repositories.vocabulary, config.nlu),
        bus,
    )
    return NluBundle(
        normalizer, matcher, scorer, vocabulary_index, binding_catalog, program_catalog, interpreter, deepseek, extractor, builder
    )


def _program_sources(config: AppConfig) -> list[ProgramSource]:
    sources: list[ProgramSource] = [SystemProgramsSource()]
    if not is_windows():
        return sources
    registry = RegistryReader()
    depth = config.programs.scan_depth
    sources.extend(
        [
            StartMenuSource(ShortcutResolver()),
            AppPathsSource(registry),
            UninstallSource(registry),
            ProgramFilesSource(depth),
            SteamSource(registry, depth),
            EpicGamesSource(),
            UwpAppsSource(),
        ]
    )
    return sources


def _com_initializer() -> Callable[[], None]:
    if not is_windows():
        return lambda: None
    import pythoncom

    pythoncom.CoInitialize()
    return pythoncom.CoUninitialize


def _build_music(config: AppConfig, repositories: Repositories, bus: EventBus, deepseek: DeepSeekClient) -> MusicService:
    ytdlp = YtDlpClient()
    scraper = YtDlpSoundCloudSearch(ytdlp)
    client_id = config.music.soundcloud_client_id
    search: TrackSearch = FallbackTrackSearch(SoundCloudApiSearch(client_id), scraper) if client_id else scraper
    player: MusicPlayer = (
        VlcPlayer(YtDlpStreamResolver(ytdlp), config.music.initial_volume)
        if config.music.backend.value == "vlc"
        else BrowserPlayer()
    )
    recommender = FallbackMusicRecommender(
        DeepSeekMusicRecommender(deepseek, repositories.preferences), LocalMusicRecommender(repositories.preferences)
    )
    return MusicService(
        search, TrackRanker(), player, recommender, repositories.preferences, repositories.listening, bus, config.music
    )


def _dialogue_status(music: MusicService, context: DialogContext) -> Callable[[], dict[str, str]]:
    def status() -> dict[str, str]:
        facts: dict[str, str] = {}
        track = music.current
        if track is not None:
            facts["now_playing"] = track.display_name
        program = context.last_program
        if program is not None:
            facts["last_app"] = program.name
        return facts

    return status


def _build_skills(
    config: AppConfig,
    paths: AppPaths,
    repositories: Repositories,
    bus: EventBus,
    scheduler: Scheduler,
    nlu: NluBundle,
    context: DialogContext,
) -> SkillBundle:
    opener = ShellOpener()
    player = AudioPlayer()
    launcher = ProgramLauncher(opener)
    alias_builder = ProgramAliasBuilder()
    input_controller = WindowsInputController()
    window_manager = Win32WindowManager()
    programs = ProgramService(nlu.program_catalog, launcher, ProcessCloser(config.programs.close_timeout_seconds), bus)
    indexer = ProgramIndexer(
        _program_sources(config),
        repositories.programs,
        alias_builder,
        on_indexed=lambda count: bus.publish(ProgramsIndexed(count)),
        com_initializer=_com_initializer,
    )
    folders, urls = FolderResolver(), UrlResolver()
    music = _build_music(config, repositories, bus, nlu.deepseek)
    reminders = ReminderService(repositories.reminders, scheduler, bus, config.reminders)
    screenshots = ScreenshotService(
        ScreenGrabber(),
        Win32ActiveWindowLocator(),
        Win32ClipboardWriter(),
        RegionSelector(bus, config.screenshots.region_timeout_seconds),
        paths.resolve(config.screenshots.directory),
        config.screenshots,
    )
    volume = PycawVolumeController()
    dialogue = DialogueEngine(
        nlu.deepseek,
        context.recent_exchanges,
        config.dialogue,
        status=_dialogue_status(music, context),
    )
    registry = SkillRegistry()
    dispatcher = SkillDispatcher(registry)
    executor = ActionExecutor(programs, opener, folders, urls, music, HotkeySender(), dispatcher.dispatch)
    registry.register_all(
        [
            AppsSkill(programs, indexer, folders, urls, opener),
            MusicSkill(music, config.music, input_controller),
            TimersSkill(TimerService(scheduler, bus, player)),
            RemindersSkill(reminders),
            ScreenshotsSkill(screenshots),
            SystemSkill(volume, WindowsPowerController(opener), config.system),
            SystemExtrasSkill(bus, volume, WindowsPowerExtras(), opener),
            WindowControlSkill(input_controller, window_manager),
            YouTubeControlSkill(input_controller, window_manager),
            YouTubePlaySkill(YtDlpYouTubeSearch(YtDlpClient()), opener),
            WebSearchSkill(opener),
            WeatherSkill(OpenMeteoClient(), config.location),
            CalculatorSkill(ExpressionTranslator(), SafeCalculator()),
            SystemInfoSkill(PsutilProbe()),
            ConversationSkill(dialogue, config.dialogue),
            PlanSkill(executor),
            BindingsSkill(repositories.bindings, executor, nlu.normalizer, bus),
        ]
    )
    return SkillBundle(dispatcher, indexer, launcher, alias_builder, reminders)


def _build_speech(config: AppConfig, paths: AppPaths, bus: EventBus, nlu: NluBundle) -> SpeechBundle:
    settings = config.speech
    models = VoskModelProvider({language: paths.resolve(path) for language, path in settings.models.items()})
    parser = VoskResultParser()
    factory = VoskRecognizerFactory(models, settings.sample_rate)
    transcriber = SpeechTranscriber(factory, parser, settings, models)
    command_transcriber, whisper_provider = _build_command_transcriber(config, paths, transcriber)
    microphone = MicrophoneStream(settings.sample_rate, settings.block_size, settings.input_device)
    wake_matcher = WakeWordMatcher(settings.wake.words, settings.wake.threshold)
    grammar = GrammarProvider(
        (
            lambda: (binding.normalized for binding in nlu.binding_catalog.all()),
            lambda: (
                alias.normalized for entry in nlu.vocabulary_index.entries() for alias in entry.word.aliases
            ),
            nlu.program_catalog.spoken_names,
        ),
        command_keywords(),
    )
    primary = settings.primary_language

    def detector_factory() -> WakeWordDetector:
        recognizer = StreamingRecognizer(
            lambda: factory.create(primary, [*wake_matcher.variants, "[unk]"]), parser, primary
        )
        return WakeWordDetector(recognizer, wake_matcher, settings.sample_rate)

    listener = VoiceListener(bus, microphone, command_transcriber, detector_factory, grammar, settings)
    player = AudioPlayer()
    edge = EdgeTtsSpeaker(config.tts, paths.resolve(config.tts.cache_dir), player)
    speaker = FallbackSpeaker(edge, Pyttsx3Speaker() if config.tts.offline_fallback else None)
    speech_service = SpeechService(bus, speaker, config.tts, warmup=edge)
    return SpeechBundle(
        microphone, models, transcriber, command_transcriber, whisper_provider, grammar, wake_matcher, listener, speech_service
    )


def _build_command_transcriber(
    config: AppConfig, paths: AppPaths, fallback: SpeechTranscriber
) -> tuple[Transcriber, WhisperModelProvider | None]:
    if config.speech.engine.value != "whisper":
        return fallback, None
    provider = WhisperModelProvider(config.speech.whisper, paths.resolve)
    preprocessor = AudioPreprocessor(config.speech.sample_rate) if config.speech.normalize_audio else None
    whisper = WhisperTranscriber(
        provider,
        config.speech.whisper,
        preprocessor,
        fallback=fallback,
        sample_rate=config.speech.sample_rate,
        min_word_confidence=config.speech.min_word_confidence,
    )
    return whisper, provider


def _build_trainer(
    config: AppConfig,
    paths: AppPaths,
    bus: EventBus,
    repositories: Repositories,
    speech: SpeechBundle,
    nlu: NluBundle,
) -> PronunciationTrainer:
    languages = [config.speech.primary_language, *config.speech.secondary_languages]
    available = [language for language in languages if language in speech.models.languages]
    return PronunciationTrainer(
        bus=bus,
        vocabulary=repositories.vocabulary,
        bindings=repositories.bindings,
        microphone=speech.microphone,
        recorder=UtteranceRecorder(config.speech.sample_rate),
        sample_transcriber=SampleTranscriber(speech.transcriber, available, config.training.alternatives),
        extractor=nlu.extractor,
        builder=nlu.builder,
        scorer=nlu.scorer,
        settings=config.training,
        voice_dir=paths.resolve(config.training.voice_dir),
    )


def safe_build(paths: AppPaths) -> Application | None:
    try:
        return build_application(paths)
    except JarvisError:
        logger.exception("Не вдалося запустити J.A.R.V.I.S.")
        return None
