"""Centralized logging for AcademicFigureGallery pipeline.

Provides structured, colored console logging with consistent formatting
across all pipeline modules.
"""

import logging
import sys

# ── Formatter with aligned, readable output ──────────────────────────

class PipelineFormatter(logging.Formatter):
    """Clean, aligned log output with optional color."""

    COLORS = {
        logging.DEBUG: "\033[90m",     # gray
        logging.INFO: "\033[0m",       # default
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        level = record.levelname[0]  # I/W/E/D
        name = record.name[:12].ljust(12)
        msg = record.getMessage()
        return f"{color}[{level}] {name} {msg}{self.RESET}"


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with pipeline formatting.

    Usage:
        from log import get_logger
        logger = get_logger("Extractor")
        logger.info("Extracted %d figures from %s", 5, "paper.pdf")
    """
    logger = logging.getLogger(f"afg.{name}")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(PipelineFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger
