# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The log file has to outlast the day it describes.

At DEBUG under ten tables the 10 MiB × 5 rotation turned over every fifteen
minutes; a table stuck at lunch could not be explained by dinner. And most of
those bytes were urllib3 announcing connections.
"""

import logging
import logging.handlers

from citizens import logging_setup
from citizens.config import get_settings


def test_the_file_keeps_a_day_and_the_libraries_stay_quiet(settings_env, monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    monkeypatch.setenv("CITIZENS_LOG_LEVEL", "DEBUG")
    get_settings.cache_clear()
    try:
        logging_setup.setup_logging(get_settings())
        rotating = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rotating) == 1
        assert rotating[0].maxBytes >= 50 * 1024 * 1024
        assert rotating[0].backupCount >= 10
        assert rotating[0].maxBytes * (rotating[0].backupCount + 1) >= 500 * 1024 * 1024
        assert root.level == logging.DEBUG, "the app's own events stay at the configured level"
        for name in logging_setup.NOISY_LIBRARIES:
            assert logging.getLogger(name).level >= logging.INFO, name
    finally:
        for handler in root.handlers[:]:
            if handler not in saved_handlers:
                root.removeHandler(handler)
                handler.close()
        for handler in saved_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(saved_level)
        get_settings.cache_clear()
