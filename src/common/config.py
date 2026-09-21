"""YAML config loading."""
from __future__ import annotations
import datetime as dt
import yaml
from .paths import CONFIG


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def to_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
