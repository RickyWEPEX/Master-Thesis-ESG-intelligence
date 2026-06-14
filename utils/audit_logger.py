"""Append-only Audit-Trail mit Hash-Verkettung.

Erfuellt NFA-2.1: Jeder Verarbeitungsschritt wird unveraenderlich
protokolliert. Manipulationssicherheit wird ueber eine SHA-256-Hashkette
gewaehrleistet (jeder Eintrag enthaelt den Hash des Vorgaengers). Eine
nachtraegliche Aenderung bricht die Kette und ist via verify() erkennbar.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.config_loader import resolve


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AuditLogger:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def log(self, agent: str, action: str, details: dict | None = None,
            confidence: float | None = None) -> dict:
        prev_hash = self._entries[-1]["hash"] if self._entries else self.GENESIS
        entry = {
            "index": len(self._entries),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            "confidence": confidence,
            "details": details or {},
            "prev_hash": prev_hash,
        }
        entry["hash"] = hashlib.sha256(
            (prev_hash + _canonical({k: entry[k] for k in entry if k != "hash"})).encode("utf-8")
        ).hexdigest()
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[dict]:
        return self._entries

    def verify(self) -> bool:
        """Prueft die Integritaet der Hashkette (append-only Garantie)."""
        prev_hash = self.GENESIS
        for entry in self._entries:
            if entry["prev_hash"] != prev_hash:
                return False
            expected = hashlib.sha256(
                (prev_hash + _canonical({k: entry[k] for k in entry if k != "hash"})).encode("utf-8")
            ).hexdigest()
            if expected != entry["hash"]:
                return False
            prev_hash = entry["hash"]
        return True

    def export(self, path: str | Path) -> Path:
        target = resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "audit_trail_version": "1.0",
            "entry_count": len(self._entries),
            "chain_valid": self.verify(),
            "entries": self._entries,
        }
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return target
