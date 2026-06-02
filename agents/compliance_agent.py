"""Compliance Agent (UC-04 / FA-3).

Prueft die Vollstaendigkeit der ESRS-Berichterstattung fuer alle wesentlichen
Standards (IG 1-konform: nur materielle Standards werden verpflichtend geprueft).
Liefert Vollstaendigkeitsgrad, Ampelstatus und priorisierte Gap-Liste je Standard.
"""
from __future__ import annotations

from agents.base import BaseAgent, ComplianceResult, ExtractedDatapoint

# Mapping: Datenpunkt-ID-Praefix -> ESRS-Standard
_PREFIX_TO_STANDARD = {
    "E1": "ESRS E1", "E2": "ESRS E2", "E3": "ESRS E3",
    "E4": "ESRS E4", "E5": "ESRS E5",
    "S1": "ESRS S1", "S2": "ESRS S2", "S3": "ESRS S3", "S4": "ESRS S4",
    "G1": "ESRS G1",
}


def _standard_of(dp_id: str) -> str:
    prefix = dp_id.split("-")[0]
    return _PREFIX_TO_STANDARD.get(prefix, "Unbekannt")


class ComplianceAgent(BaseAgent):
    name = "ComplianceAgent"

    def __init__(self, audit, catalog: dict,
                 green_threshold: float = 0.90, yellow_threshold: float = 0.70,
                 material_standards: list[str] | None = None) -> None:
        super().__init__(audit)
        self.catalog = catalog
        self.green = green_threshold
        self.yellow = yellow_threshold
        # Nur wesentliche Standards werden auf Pflichtangaben geprueft (IG 1-konform).
        # None = alle Standards pruefen (Fallback fuer Tests ohne Materialitaet).
        self.material_standards = material_standards

    def run(self, extracted: list[ExtractedDatapoint]) -> ComplianceResult:
        self._log("compliance_check_started",
                  {"material_standards": self.material_standards})
        by_id = {e.id: e for e in extracted}

        all_mandatory = [dp for dp in self.catalog["datapoints"] if dp.get("mandatory")]

        # Filtere auf wesentliche Standards (IG 1: nur materielle Standards berichtspflichtig)
        if self.material_standards is not None:
            mandatory = [dp for dp in all_mandatory
                         if _standard_of(dp["id"]) in self.material_standards]
        else:
            mandatory = all_mandatory

        gaps, present = [], 0
        for dp in mandatory:
            e = by_id.get(dp["id"])
            if e is not None and e.present:
                present += 1
            else:
                gaps.append({
                    "id": dp["id"],
                    "dr": dp["dr"],
                    "name_de": dp["name_de"],
                    "standard": _standard_of(dp["id"]),
                })

        total = len(mandatory)
        rate = present / total if total else 1.0
        status = "GRUEN" if rate >= self.green else ("GELB" if rate >= self.yellow else "ROT")

        result = ComplianceResult(
            total_mandatory=total, present_mandatory=present,
            completeness_rate=round(rate, 4), status=status, gaps=gaps,
        )
        self._log("compliance_check_completed",
                  {"completeness_rate": result.completeness_rate, "status": status,
                   "gaps": len(gaps), "standards_checked": len(self.material_standards or [])})
        return result
