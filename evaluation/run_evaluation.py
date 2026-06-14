"""Evaluations-Runner (UC-07).

Fuehrt den vollstaendigen Workflow auf den synthetischen Datensaetzen aus und
berechnet die Metriken fuer die Hypothesenpruefung. Ergebnis wird als
evaluation_results.json gespeichert und tabellarisch ausgegeben.

Aufruf:  python -m evaluation.run_evaluation
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.orchestrator import Orchestrator
from evaluation.metrics import extraction_metrics, validation_metrics
from evaluation.ml_classifier import run_ml_evaluation
from utils.config_loader import load_json, save_json

CLEAN = "data/synthetic/synthetic_company_data.json"
ERRORS = "data/synthetic/synthetic_company_data_errors.json"
GT = "data/ground_truth/ground_truth.json"
VAL_GT = "data/ground_truth/validation_ground_truth.json"


def main() -> dict:
    orch = Orchestrator()

    # --- H2a / H2b / H1a auf dem sauberen Datensatz ----------------------
    clean = orch.run(CLEAN)
    ext = extraction_metrics(clean["extracted"], load_json(GT))

    # --- FA-2 / H2b: Fehlererkennung auf der Fehler-Variante -------------
    orch_err = Orchestrator()
    errors = orch_err.run(ERRORS)
    val = validation_metrics(errors["validation_issues"], load_json(VAL_GT))

    # Compliance-Gap-Erkennung (fehlende Pflichtangabe)
    val_gt = load_json(VAL_GT)
    expected_gaps = {g["datapoint_id"] for g in val_gt.get("expected_completeness_gaps", [])}
    detected_gaps = {g["id"] for g in errors["compliance"].gaps}
    gap_recall = len(expected_gaps & detected_gaps) / len(expected_gaps) if expected_gaps else 1.0

    # --- H2d: ML-Klassifikator + SHAP ------------------------------------
    ml = run_ml_evaluation()

    # --- H3a: YAML-Konfigurierbarkeit (neue Datenpunkte ohne Code) -------
    from utils.config_loader import load_yaml, load_settings
    _settings = load_settings()
    _all_catalogs_paths = [_settings["paths"]["datapoint_catalog"]] + \
        _settings["paths"].get("additional_catalogs", [])
    _all_dps = []
    for _p in _all_catalogs_paths:
        _all_dps.extend(load_yaml(_p).get("datapoints", []))
    total_dps = len(_all_dps)
    # H3a: nur explizit hinzugefuegte Demo-DPs (E1-DP-035 bis E1-DP-044)
    new_dps = [dp for dp in _all_dps
               if dp["id"].startswith("E1-DP-") and dp["id"] >= "E1-DP-035"]
    h3a_neue_datenpunkte = len(new_dps)
    # H3b: Agenten-Wiederverwendungsrate (Design-Analyse, nicht datenpunktbasiert).
    # 6 Kern-Agenten werden standarduebergreifend eingesetzt; Anpassung erfolgt ausschliesslich
    # ueber YAML/JSON-Konfiguration, nicht ueber Quellcode (DP-2, NFA-3).
    # Voll-Wiederverwendung OHNE jede Konfiguration: Extraction, Compliance, Materiality, Report.
    # Validation (validation_rules.yaml deckt E1,E2,E3,E5,G1,S1,S2 ab) und Assessment
    # (sector_benchmarks.json deckt E1,E2,E3,E5,G1,S1,S2,S4 ab) sind ebenfalls standarduebergreifend,
    # erfordern jedoch standardspezifische YAML-Eintraege.
    # Berichteter Wert: konservative Voll-Reuse-Quote 4/6 = 66.7% (Thesis Abschnitt 6.2.4).
    # Auf eine gewichtete Gesamtquote wird bewusst verzichtet (nicht objektiv messbar).
    h3b_wiederverwendungsrate = 66.7

    # --- Assessment-Bewertung aus sauberem Lauf --------------------------
    assessment = clean.get("assessment")
    assessment_dict = assessment.to_dict() if assessment else {}

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": orch.settings["run"]["extraction_backend"],
        "H1a_runtime_seconds_clean": clean["elapsed_seconds"],
        "H2a_extraction": ext.to_dict(),
        "H2b_completeness_clean": clean["compliance"].to_dict(),
        "FA2_validation_error_detection": val.to_dict(),
        "FA31_compliance_gap_recall": round(gap_recall, 4),
        "H2d_ml_classifier": ml.to_dict(),
        "H3a_neue_datenpunkte_via_yaml": h3a_neue_datenpunkte,
        "H3a_gesamte_datenpunkte": total_dps,
        "H3b_wiederverwendungsrate_pct": h3b_wiederverwendungsrate,
        "assessment_gesamtampel": assessment_dict.get("gesamtampel", "n/a"),
        "audit_chain_valid": clean["audit_valid"] and errors["audit_valid"],
        "targets": {
            "H2a_f1": 0.85, "H2b_completeness": 0.90,
            "FA2_detection_rate": 0.95, "FA2_false_positive_rate_max": 0.10,
            "H2d_cv_f1": 0.80, "H3a_neue_dps": 10, "H3b_reuse_pct": 30,
        },
    }
    save_json("output/evaluation_results.json", results)
    _print_summary(results, ext, val, ml, h3a_neue_datenpunkte, h3b_wiederverwendungsrate)
    return results


def _check(value: float, target: float, higher_better: bool = True) -> str:
    ok = value >= target if higher_better else value <= target
    return "ERFUELLT" if ok else "NICHT ERFUELLT"


def _print_summary(results: dict, ext, val, ml,
                   h3a_neue: int = 0, h3b_reuse: float = 0.0) -> None:
    print("\n" + "=" * 64)
    print(" EVALUATION - KI-Agenten-Framework ESG (CSRD/ESRS, alle Standards)")
    print("=" * 64)
    print(f" Backend:                 {results['backend']}")
    print(f" Audit-Kette gueltig:     {results['audit_chain_valid']}")
    print(f" Durchlaufzeit (H1a):     {results['H1a_runtime_seconds_clean']} s")
    print("-" * 64)
    print(f" H2a Precision:           {ext.precision}")
    print(f" H2a Recall:              {ext.recall}")
    print(f" H2a F1-Score:            {ext.f1}   [Ziel >=0.85: {_check(ext.f1, 0.85)}]")
    print(f" H2b Vollstaendigkeit:    {results['H2b_completeness_clean']['completeness_rate']}"
          f"   [Ziel >=0.90: {_check(results['H2b_completeness_clean']['completeness_rate'], 0.90)}]")
    print("-" * 64)
    print(f" FA-2 Erkennungsrate:     {val.detection_rate}"
          f"   [Ziel >=0.95: {_check(val.detection_rate, 0.95)}]")
    print(f" FA-2 False-Positive:     {val.false_positive_rate}"
          f"   [Ziel <=0.10: {_check(val.false_positive_rate, 0.10, higher_better=False)}]")
    print(f" FA-3.1 Gap-Erkennung:    {results['FA31_compliance_gap_recall']}")
    print("-" * 64)
    top_feat = next(iter(ml.shap_mean_abs))
    print(f" H2d CV-F1 (RF+SHAP):    {ml.cv_f1_mean} +/- {ml.cv_f1_std}"
          f"   [Ziel >=0.80: {_check(ml.cv_f1_mean, 0.80)}]")
    print(f" H2d Wichtigstes Merkmal: {top_feat} "
          f"(SHAP={ml.shap_mean_abs[top_feat]})")
    print("-" * 64)
    print(f" H3a Neue DPs via YAML:   {h3a_neue}   [Ziel >=10: {_check(h3a_neue, 10)}]")
    print(f" H3b Wiederverwendung:    {h3b_reuse}%  [Ziel >=30%: {_check(h3b_reuse, 30.0)}]")
    print(f" H3c Konfigurierbarkeit:  YAML+Streamlit (qualitativ nachgewiesen)")
    print("=" * 64)
    print(" Ergebnis gespeichert: output/evaluation_results.json\n")


if __name__ == "__main__":
    main()
