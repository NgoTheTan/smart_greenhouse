"""Logging thống nhất cho api và worker."""

import logging

from core.config import get_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
