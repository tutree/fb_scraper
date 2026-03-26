import logging
import sys
from collections import deque
from threading import Lock
from typing import List

import colorlog

_LOG_BUFFER = deque(maxlen=5000)
_LOG_BUFFER_LOCK = Lock()


class InMemoryLogHandler(logging.Handler):
    """Capture recent logs in memory for dashboard streaming."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with _LOG_BUFFER_LOCK:
                _LOG_BUFFER.append(msg)
        except Exception:
            # Never break logging due to in-memory buffer issues
            pass


def _plain_log_format() -> str:
    return (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )


def _stdout_colored_formatter() -> colorlog.ColoredFormatter:
    """Level label (INFO, WARNING, …) uses secondary_log_colors; INFO = green."""
    return colorlog.ColoredFormatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname_log_color)s%(levelname)-8s%(reset)s | "
            "%(cyan)s%(name)s%(reset)s:"
            "%(blue)s%(funcName)s%(reset)s:"
            "%(lineno)d - %(message)s"
        ),
        datefmt=None,
        reset=True,
        log_colors={},
        secondary_log_colors={
            "levelname": {
                "DEBUG": "cyan",
                "INFO": "bold,green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        },
    )


def setup_logging(level: str = "INFO") -> None:
    """Configure application-wide logging."""
    plain = _plain_log_format()

    # Create handlers with explicit flushing
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    stdout_handler.setFormatter(_stdout_colored_formatter())
    memory_handler = InMemoryLogHandler()
    memory_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    # No ANSI in buffer — used for API/dashboard log streaming
    memory_handler.setFormatter(logging.Formatter(plain))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers = []  # Clear existing handlers
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(memory_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    # Force unbuffered output
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    
    print("=" * 80, flush=True)
    print("LOGGING SYSTEM INITIALIZED", flush=True)
    print("=" * 80, flush=True)
    logging.info("Logging system initialized")


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(name)


def get_recent_logs(lines: int = 200) -> List[str]:
    """Return the latest log lines from in-memory buffer."""
    safe_lines = max(1, min(lines, 2000))
    with _LOG_BUFFER_LOCK:
        return list(_LOG_BUFFER)[-safe_lines:]
