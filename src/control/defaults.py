"""Shared UI/backend defaults; applied only when creating a new Campaign."""
import json
from pathlib import Path

DEFAULTS = json.loads((Path(__file__).resolve().parents[2] / 'schemas/meta-defaults.json').read_text())
DEFAULT_OBJECTIVE = DEFAULTS['objective']


def effective_objective(config):
    value = config.get('objective')
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_OBJECTIVE
