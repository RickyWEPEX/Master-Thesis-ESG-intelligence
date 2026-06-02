"""Evaluationsmetriken (UC-07).

Berechnet die fuer die Hypothesenpruefung benoetigten Kennzahlen:
* Extraktion (H2a): Precision, Recall, F1 gegen Ground Truth
* Vollstaendigkeit (H2b): Anteil korrekt befuellter verfuegbarer Datenpunkte
* Validierung (FA-2/H2b): Fehlererkennungsrate und False-Positive-Rate

Deterministisch und reproduzierbar (QA-3.1): identische Inputs -> identische Metriken.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ExtractionMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    completeness: float
    n_ground_truth: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationMetrics:
    expected: int
    detected: int
    extra: int
    detection_rate: float
    false_positive_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def _values_match(gt_value, ex_value, tol: float) -> bool:
    if gt_value == "NARRATIVE":
        return ex_value is not None and str(ex_value).strip() != ""
    if isinstance(gt_value, (int, float)) and isinstance(ex_value, (int, float)):
        return abs(float(ex_value) - float(gt_value)) <= tol * max(abs(float(gt_value)), 1.0)
    return gt_value == ex_value


def extraction_metrics(extracted, ground_truth: dict) -> ExtractionMetrics:
    """extracted: Liste von ExtractedDatapoint; ground_truth: geladenes ground_truth.json"""
    gt = ground_truth["datapoints"]
    tol = ground_truth.get("_meta", {}).get("numeric_tolerance", 0.01)
    by_id = {e.id: e for e in extracted}

    tp = fp = fn = 0
    n_gt_present = 0
    for dp_id, gt_entry in gt.items():
        gt_present = gt_entry.get("present", False)
        if gt_present:
            n_gt_present += 1
        e = by_id.get(dp_id)
        ex_present = bool(e and e.present)
        correct = ex_present and gt_present and _values_match(gt_entry.get("value"), e.value, tol)

        if gt_present and ex_present and correct:
            tp += 1
        elif gt_present and ex_present and not correct:
            fp += 1
            fn += 1
        elif gt_present and not ex_present:
            fn += 1
        elif not gt_present and ex_present:
            fp += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    completeness = tp / n_gt_present if n_gt_present else 0.0

    return ExtractionMetrics(
        true_positives=tp, false_positives=fp, false_negatives=fn,
        precision=round(precision, 4), recall=round(recall, 4), f1=round(f1, 4),
        completeness=round(completeness, 4), n_ground_truth=n_gt_present,
    )


def validation_metrics(issues, validation_ground_truth: dict) -> ValidationMetrics:
    """issues: Liste von ValidationIssue; validation_ground_truth: geladenes JSON"""
    expected = validation_ground_truth.get("expected_issues", [])
    matched_expected = 0
    matched_issue_keys = set()

    for exp in expected:
        for idx, issue in enumerate(issues):
            same_check = issue.check == exp["check"]
            same_path = ("path" not in exp) or (issue.path == exp["path"])
            if same_check and same_path:
                matched_expected += 1
                matched_issue_keys.add(idx)
                break

    extra = sum(1 for idx in range(len(issues)) if idx not in matched_issue_keys)
    detection_rate = matched_expected / len(expected) if expected else 1.0
    fp_rate = extra / len(issues) if issues else 0.0

    return ValidationMetrics(
        expected=len(expected), detected=matched_expected, extra=extra,
        detection_rate=round(detection_rate, 4), false_positive_rate=round(fp_rate, 4),
    )
