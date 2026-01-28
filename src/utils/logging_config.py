import logging
import sys

# Root logger configuration
def setup_logger(name: str = "makerates", level: int = logging.INFO) -> logging.Logger:
    """
    Returns a configured logger with stream handler and formatter.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding multiple handlers if already configured
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        logger.propagate = False

    return logger

# Optional: automatically configure root logger when imported
root_logger = setup_logger()
