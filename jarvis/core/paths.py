from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE_NAME = "config.yaml"
ENV_FILE_NAME = ".env"


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    package_dir: Path

    @classmethod
    def detect(cls) -> AppPaths:
        package_dir = cls._package_dir()
        if getattr(sys, "frozen", False):
            return cls(base_dir=Path(sys.executable).resolve().parent, package_dir=package_dir)
        return cls(base_dir=package_dir.parent, package_dir=package_dir)

    @staticmethod
    def _package_dir() -> Path:
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir is not None:
            return Path(bundle_dir) / "jarvis"
        return Path(__file__).resolve().parent.parent

    @property
    def user_config_file(self) -> Path:
        return self.base_dir / CONFIG_FILE_NAME

    @property
    def default_config_file(self) -> Path:
        return self.package_dir / CONFIG_FILE_NAME

    @property
    def env_file(self) -> Path:
        return self.base_dir / ENV_FILE_NAME

    def resolve(self, path: Path) -> Path:
        expanded = path.expanduser()
        if expanded.is_absolute():
            return expanded
        return (self.base_dir / expanded).resolve()
