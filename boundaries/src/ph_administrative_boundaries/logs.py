"""Structured logging: readable lines in a terminal, JSON lines for Loki."""

import logging
import sys
from enum import StrEnum

import structlog


class LogFormat(StrEnum):
    console = "console"
    json = "json"


def configure_logging(fmt: LogFormat = LogFormat.console, quiet: bool = False) -> None:
    """Send every log event to stderr, keeping stdout for build results."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if fmt is LogFormat.json
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.WARNING if quiet else logging.INFO
        ),
        logger_factory=lambda *_: structlog.PrintLogger(sys.stderr),
        cache_logger_on_first_use=False,
    )
