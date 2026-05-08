from src.utils.logger import setup_logger
from src.core.config_loader import load_config


def initialize_system():

    logger = setup_logger()

    try:

        config = load_config()

        logger.info(f"System Name: {config['project']['name']}")
        logger.info(f"Environment: {config['project']['environment']}")
        logger.info("ICT AI Trading Intelligence System Initialized")

    except Exception as error:

        logger.exception(f"System initialization failed: {error}")


if __name__ == "__main__":
    initialize_system()
    