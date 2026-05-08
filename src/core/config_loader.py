import json
import sys
from typing import Dict


CONFIG_PATH = "10_CONFIG/settings.json"


def load_config() -> Dict:
    """
    Load system configuration safely.
    """

    try:

        with open(CONFIG_PATH, "r") as config_file:
            config = json.load(config_file)

        return config

    except FileNotFoundError:

        print(f"[CONFIG ERROR] Missing config file: {CONFIG_PATH}")
        sys.exit(1)

    except json.JSONDecodeError:

        print("[CONFIG ERROR] Invalid JSON format in settings.json")
        sys.exit(1)

    except Exception as error:

        print(f"[CONFIG ERROR] Unexpected error: {error}")
        sys.exit(1)
        