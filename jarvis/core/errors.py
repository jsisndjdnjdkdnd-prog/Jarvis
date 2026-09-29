class JarvisError(Exception):
    pass


class ConfigError(JarvisError):
    pass


class StorageError(JarvisError):
    pass


class AudioDeviceError(JarvisError):
    pass


class RecognitionError(JarvisError):
    pass


class ModelNotFoundError(RecognitionError):
    pass


class SpeechSynthesisError(JarvisError):
    pass


class SkillError(JarvisError):
    pass


class SkillNotFoundError(SkillError):
    pass


class ProgramNotFoundError(SkillError):
    def __init__(self, program_name: str) -> None:
        super().__init__(program_name)
        self.program_name = program_name


class ActionExecutionError(SkillError):
    pass


class MusicError(SkillError):
    pass


class TrackNotFoundError(MusicError):
    pass


class PlatformNotSupportedError(SkillError):
    pass


class DeepSeekError(JarvisError):
    pass


class DeepSeekUnavailableError(DeepSeekError):
    pass


class InvalidModelResponseError(DeepSeekError):
    pass


class TrainingError(JarvisError):
    pass


class NotEnoughSamplesError(TrainingError):
    pass


class EmptyRecordingError(TrainingError):
    pass


class TimeParseError(JarvisError):
    pass
