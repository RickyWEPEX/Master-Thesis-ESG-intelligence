"""Gemeinsame Datenstrukturen und Basisklasse fuer alle Agenten."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from utils.audit_logger import AuditLogger


@dataclass
class ExtractedDatapoint:
    id: str
    dr: str
    name_de: str
    category: str
    datatype: str
    unit: str
    value: Any
    present: bool
    confidence: float
    source: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationIssue:
    check: str
    path: str
    severity: str          # critical | warning | info
    message: str
    datapoint_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComplianceResult:
    total_mandatory: int
    present_mandatory: int
    completeness_rate: float
    status: str            # GRUEN | GELB | ROT
    gaps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class BaseAgent:
    """Basisklasse: Name + Zugriff auf den gemeinsamen Audit-Trail (DP-6)."""

    name: str = "BaseAgent"

    def __init__(self, audit: AuditLogger) -> None:
        self.audit = audit

    def _log(self, action: str, details: dict | None = None,
             confidence: float | None = None) -> None:
        self.audit.log(self.name, action, details=details, confidence=confidence)
