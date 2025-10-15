import logging
import sys

logging.basicConfig()

logger: logging.Logger = logging.getLogger("epicsdbtools")


class ColorFormatter(logging.Formatter):
    """ANSI color formatter for warnings and errors."""

    COLOR_MAP = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33;1m",  # Bright Yellow
        logging.ERROR: "\033[31;1m",  # Bright Red
        logging.CRITICAL: "\033[41;97m",  # White on Red bg
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, use_color: bool = True):
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if self.use_color and record.levelno in self.COLOR_MAP:
            return f"{self.COLOR_MAP[record.levelno]}{base}{self.RESET}"
        return base


handler = logging.StreamHandler()
use_color = sys.stderr.isatty()
fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
handler.setFormatter(ColorFormatter(fmt, use_color=use_color))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
