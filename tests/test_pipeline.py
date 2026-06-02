"""Unit- und Integrationstests fuer den vertikalen E1-Slice."""
from __future__ import annotations

from agents.orchestrator import Orchestrator
from evaluation.metrics import extraction_metrics, validation_metrics
from utils.audit_logger import AuditLogger
from utils.config_loader import load_json

CLEAN = "data/synthetic/synthetic_company_data.json"
ERRORS = "data/synthetic/synthetic_company_data_errors.json"


def test_audit_chain_integrity_and_tamper_detection():
    log = AuditLogger()
    log.log("A", "step1", {"x": 1})
    log.log("A", "step2", {"y": 2})
    assert log.verify() is True
    # Manipulation bricht die Kette
    log.entries[0]["details"]["x"] = 999
    assert log.verify() is False


def test_clean_run_completeness_and_audit():
    result = Orchestrator().run(CLEAN)
    assert result["audit_valid"] is True
    assert result["compliance"].completeness_rate == 1.0
    assert result["compliance"].status == "GRUEN"
    # Keine kritischen Validierungsfehler im sauberen Datensatz
    assert all(i.severity != "critical" for i in result["validation_issues"])


def test_extraction_metrics_meet_target_on_clean():
    result = Orchestrator().run(CLEAN)
    metrics = extraction_metrics(result["extracted"], load_json("data/ground_truth/ground_truth.json"))
    assert metrics.f1 >= 0.85
    assert metrics.completeness >= 0.90


def test_validation_detects_injected_errors():
    result = Orchestrator().run(ERRORS)
    val_gt = load_json("data/ground_truth/validation_ground_truth.json")
    metrics = validation_metrics(result["validation_issues"], val_gt)
    assert metrics.detection_rate >= 0.95
    assert metrics.false_positive_rate <= 0.10


def test_compliance_gap_detected_on_errors():
    result = Orchestrator().run(ERRORS)
    gap_ids = {g.get("id") or g.get("datapoint_id") for g in result["compliance"].gaps}
    assert "E1-DP-030" in gap_ids  # fehlendes Pflicht-Narrativ E1-2


def test_determinism_repeated_runs():
    r1 = extraction_metrics(Orchestrator().run(CLEAN)["extracted"],
                            load_json("data/ground_truth/ground_truth.json"))
    r2 = extraction_metrics(Orchestrator().run(CLEAN)["extracted"],
                            load_json("data/ground_truth/ground_truth.json"))
    assert r1.to_dict() == r2.to_dict()
