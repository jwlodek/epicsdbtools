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
        if self.use_color and record.levelno in self.COLOR_MAP:
            # Temporarily modify the levelname with color codes
            original_levelname = record.levelname
            # Pad to 8 characters (length of "CRITICAL") for consistent alignment
            padded_levelname = original_levelname.ljust(8)
            record.levelname = (
                f"{self.COLOR_MAP[record.levelno]}{padded_levelname}{self.RESET}"
            )
            base = super().format(record)
            # Restore the original levelname
            record.levelname = original_levelname
            return base
        # For non-colored output, still pad for consistency
        original_levelname = record.levelname
        record.levelname = original_levelname.ljust(8)
        base = super().format(record)
        record.levelname = original_levelname
        return base


handler = logging.StreamHandler()
use_color = sys.stderr.isatty()
fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
handler.setFormatter(ColorFormatter(fmt, use_color=use_color))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG) # By default, hide debug/info messages
logger.propagate = False

def set_log_level(level: int) -> None:
    """Set the logging level for the epicsdbtools logger."""
    logger.setLevel(level)
