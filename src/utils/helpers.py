from pathlib import Path
import yaml
from typing import Dict

def load_config(config_name: str) -> Dict:
    """
    Load a YAML configuration file from the 'config' directory.
    
    Args:
        config_name: Filename (e.g. 'apis.yaml', 'storage.yaml')
    """
    # Assuming standard structure: src/utils/helpers.py -> src/config/
    path = Path(__file__).parent.parent / "config" / config_name
    
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"Config {config_name} must be a dictionary at the top level")
    
    return config


