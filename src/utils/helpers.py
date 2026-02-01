from pathlib import Path
import yaml
from typing import Dict,Any
from utils.logging_config import root_logger as logger
import os,sys

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

def parse_env_vars_config(job_config: Dict[str, Any]) -> Dict[str, str]:
    """
    Parse environment variables based on settings.yaml config.
    Applies defaults and checks for required variables.
    """
    env_vars = job_config.get('env_vars', {})
    required = env_vars.get('required', [])
    optional = env_vars.get('optional', [])
    defaults = job_config.get('defaults', {})
    
    parsed_config = {}
    
    # Process all potential keys
    all_keys = set(required + optional)
    
    for key in all_keys:
        # Get from env, then default, then None
        val = os.getenv(key, defaults.get(key))
        
        parsed_config[key] = val
    
    # Check required
    missing = [key for key in required if not parsed_config.get(key)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
        
    return parsed_config


