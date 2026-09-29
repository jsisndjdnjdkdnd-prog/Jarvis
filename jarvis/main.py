from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from jarvis.bootstrap import safe_build
from jarvis.core.paths import AppPaths


def main() -> int:
    paths = AppPaths.detect()
    load_dotenv(paths.env_file)
    logging.basicConfig(level=logging.INFO)
    application = safe_build(paths)
    if application is None:
        return 1
    application.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
