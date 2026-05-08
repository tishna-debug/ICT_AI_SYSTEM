import logging
import os

from src.core.config_loader import load_config


config = load_config()

LOG_DIRECTORY = config["logging"]["log_directory"]
LOG_FILE = config["logging"]["log_file"]


def setup_logger():
    """
    Configure centralized system logger.
    """

    os.makedirs(LOG_DIRECTORY, exist_ok=True)

    log_path = os.path.join(LOG_DIRECTORY, LOG_FILE)

    logger = logging.getLogger("ICT_AI_SYSTEM")

    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers
    if not logger.handlers:

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger