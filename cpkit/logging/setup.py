"""Logging configuration for operational messages."""

import logging
import sys
import time
from typing import Any

from cpkit.settings import FrameworkSettingKey

from .context import RequestIDFilter, ShorthandFormatter


def configure_logging(
    settings_provider=None,
    *,
    force: bool = False,
    default_level: str = "INFO",
    default_journald_identifier: str = "app",
    level_key: Any = FrameworkSettingKey.logging_level,
    journald_identifier_key: Any = FrameworkSettingKey.logging_journald_identifier,
) -> None:
    """Configure root logging with journald when available."""

    if getattr(configure_logging, "_configured", False) and not force:
        return

    level_name = _setting_value(settings_provider, level_key, default_level).upper()
    journald_identifier = _setting_value(
        settings_provider,
        journald_identifier_key,
        default_journald_identifier,
    )
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").setLevel(logging.ERROR)

    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    elif root_logger.handlers:
        configure_logging._configured = True
        return

    formatter = ShorthandFormatter(
        "%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s"
    )
    formatter.converter = time.gmtime
    formatter.default_msec_format = "%s.%03d"

    handler: logging.Handler
    try:
        if sys.platform != "linux":
            raise RuntimeError("journald unavailable")

        from systemd.journal import JournalHandler

        handler = JournalHandler(SYSLOG_IDENTIFIER=journald_identifier)
    except Exception:
        handler = logging.StreamHandler()

    handler.addFilter(RequestIDFilter())
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    configure_logging._configured = True


def _setting_value(settings_provider, key: Any, default: str) -> str:
    if settings_provider is None:
        return default

    setting = settings_provider.get_setting(key)
    value = getattr(setting, "value", setting)
    if value in (None, ""):
        return default
    return str(value)
