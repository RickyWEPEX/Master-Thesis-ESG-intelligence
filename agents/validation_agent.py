"""Validation Agent (UC-03 / FA-2).

Prueft extrahierte Daten gegen Typ-/Wertgrenzen (Katalog) und konfigurierbare
Plausibilitaets-/Konsistenzregeln (validation_rules.yaml). Liefert kategorisierte
Issues (critical/warning/info) mit Erklaerung und Quellenangabe (NFA-1.1).
Die Regeln sind ohne Code-Aenderung erweiterbar (NFA-3.2 / H3a).
"""
from __future__ import annotations

from agents.base import BaseAgent, ValidationIssue
from utils.config_loader import get_by_path


def _num(data: dict, path: str):
    val = get_by_path(data, path)
    if isinstance(val, bool):
        return None
    return val if isinstance(val, (int, float)) else None


class ValidationAgent(BaseAgent):
    name = "ValidationAgent"

    def __init__(self, audit, catalog: dict, rules: dict) -> None:
        super().__init__(audit)
        self.catalog = catalog
        self.rules = rules
        self.default_tol = rules.get("metadata", {}).get("default_tolerance", 0.02)

    def run(self, company_data: dict) -> list[ValidationIssue]:
        self._log("validation_started")
        issues: list[ValidationIssue] = []
        for rule in self.rules.get("rules", []):
            issues.extend(self._apply_rule(rule, company_data))
        crit = sum(1 for i in issues if i.severity == "critical")
        self._log("validation_completed",
                  {"issues_total": len(issues), "critical": crit})
        return issues

    # -- Regeltypen ---------------------------------------------------------
    def _apply_rule(self, rule: dict, data: dict) -> list[ValidationIssue]:
        rtype = rule.get("type")
        handler = {
            "catalog_bounds": self._catalog_bounds,
            "sum_equals": self._sum_equals,
            "derived_equals": self._derived_equals,
            "relation": self._relation,
            "non_negative": self._non_negative,
            "range": self._range,
        }.get(rtype)
        if handler is None:
            return []
        return handler(rule, data)

    def _within_tol(self, a: float, b: float, tol: float) -> bool:
        return abs(a - b) <= tol * max(abs(b), 1.0)

    def _issue(self, rule: dict, path: str, dp_id: str | None = None) -> ValidationIssue:
        return ValidationIssue(
            check=rule["id"], path=path, severity=rule.get("severity", "warning"),
            message=rule.get("message_de", rule.get("description_de", rule["id"])),
            datapoint_id=dp_id,
        )

    def _catalog_bounds(self, rule: dict, data: dict) -> list[ValidationIssue]:
        out: list[ValidationIssue] = []
        for dp in self.catalog["datapoints"]:
            bounds = dp.get("validation")
            if not bounds:
                continue
            val = _num(data, dp["value_path"])
            if val is None:
                continue
            if ("min" in bounds and val < bounds["min"]) or ("max" in bounds and val > bounds["max"]):
                out.append(ValidationIssue(
                    check="catalog_bounds", path=dp["value_path"],
                    severity=rule.get("severity", "critical"),
                    message=f"{dp['name_de']}: Wert {val} {dp.get('unit','')} verletzt Grenzen {bounds}.",
                    datapoint_id=dp["id"],
                ))
        return out

    def _sum_equals(self, rule: dict, data: dict) -> list[ValidationIssue]:
        comps = [_num(data, p) for p in rule["components"]]
        target = _num(data, rule["target"])
        if target is None or any(c is None for c in comps):
            return []
        tol = rule.get("tolerance", self.default_tol)
        if not self._within_tol(sum(comps), target, tol):
            return [self._issue(rule, rule["target"])]
        return []

    def _derived_equals(self, rule: dict, data: dict) -> list[ValidationIssue]:
        num = _num(data, rule["numerator"])
        den = _num(data, rule["denominator"])
        target = _num(data, rule["target"])
        if None in (num, den, target) or den == 0:
            return []
        computed = (num / den) * 100 if rule.get("expr") == "ratio_percent" else num / den
        tol = rule.get("tolerance", self.default_tol)
        if not self._within_tol(computed, target, tol):
            return [self._issue(rule, rule["target"])]
        return []

    def _relation(self, rule: dict, data: dict) -> list[ValidationIssue]:
        if "left_sum" in rule:
            parts = [_num(data, p) for p in rule["left_sum"]]
            if any(p is None for p in parts):
                return []
            left = sum(parts)
            left_path = rule["left_sum"][0]
        else:
            left = _num(data, rule["left"])
            left_path = rule.get("left", rule.get("target", ""))
        left_path = rule.get("report_path", left_path)
        right = _num(data, rule["right"])
        if left is None or right is None:
            return []
        tol = rule.get("tolerance", 0.0)
        slack = tol * max(abs(right), 1.0)
        op = rule["op"]
        ok = {
            "lt": left < right,
            "le": left <= right + slack,
            "gt": left > right,
            "ge": left >= right - slack,
        }.get(op, True)
        return [] if ok else [self._issue(rule, left_path)]

    def _non_negative(self, rule: dict, data: dict) -> list[ValidationIssue]:
        out = []
        for path in rule.get("paths", []):
            val = _num(data, path)
            if val is not None and val < 0:
                out.append(self._issue(rule, path))
        return out

    def _range(self, rule: dict, data: dict) -> list[ValidationIssue]:
        val = _num(data, rule["path"])
        if val is None:
            return []
        if val < rule.get("min", float("-inf")) or val > rule.get("max", float("inf")):
            return [self._issue(rule, rule["path"])]
        return []
