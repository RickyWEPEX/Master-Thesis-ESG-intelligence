"""Konfigurations- und Datei-Hilfsfunktionen.

Zentralisiert das Laden von YAML/JSON sowie den Zugriff auf verschachtelte
Werte ueber Punktnotation (value_path im Datenpunktkatalog).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve(path: str | Path) -> Path:
    """Loest einen ggf. relativen Pfad gegen die Projektwurzel auf."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_yaml(path: str | Path) -> dict:
    with open(resolve(path), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: str | Path) -> dict:
    with open(resolve(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str | Path, data: Any) -> None:
    target = resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_settings(path: str | Path = "config/settings.yaml") -> dict:
    return load_yaml(path)


_MISSING = object()


def get_by_path(data: dict, dotted_path: str) -> Any:
    """Liest einen verschachtelten Wert ('a.b.c'). Gibt None zurueck, wenn nicht vorhanden."""
    current: Any = data
    for key in dotted_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def path_exists(data: dict, dotted_path: str) -> bool:
    current: Any = data
    for key in dotted_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return False
    return True
