"""CLI-Entrypoint des KI-Agenten-Frameworks fuer ESG-Reporting (CSRD/ESRS, alle Standards).

Beispiele:
  python main.py --input data/synthetic/synthetic_company_data.json
  python main.py --input data/synthetic/synthetic_company_data_errors.json
  python main.py --eval
  python main.py --input <datei> --backend claude
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="KI-Agenten-Framework fuer ESG-Reporting (CSRD/ESRS)")
    parser.add_argument("--input", default="data/synthetic/synthetic_company_data.json",
                        help="Pfad zur Unternehmensdaten-JSON")
    parser.add_argument("--output", default=None, help="Ausgabeverzeichnis (Default aus settings.yaml)")
    parser.add_argument("--settings", default="config/settings.yaml", help="Pfad zur settings.yaml")
    parser.add_argument("--backend", choices=["deterministic", "claude"], default=None,
                        help="Extraktions-Backend (ueberschreibt settings.yaml)")
    parser.add_argument("--eval", action="store_true", help="Vollstaendige Evaluation ausfuehren")
    args = parser.parse_args()

    if args.eval:
        from evaluation.run_evaluation import main as run_eval
        run_eval()
        return

    orch = Orchestrator(args.settings)
    if args.backend:
        orch.settings["run"]["extraction_backend"] = args.backend

    result = orch.run(args.input, args.output)
    comp = result["compliance"]
    crit = sum(1 for i in result["validation_issues"] if i.severity == "critical")

    print("\n" + "=" * 60)
    print(" ESG-Workflow abgeschlossen (CSRD/ESRS, alle Standards)")
    print("=" * 60)
    print(f" Backend:               {orch.settings['run']['extraction_backend']}")
    print(f" Durchlaufzeit:         {result['elapsed_seconds']} s")
    print(f" Extrahierte Punkte:    {sum(1 for e in result['extracted'] if e.present)}/"
          f"{len(result['extracted'])}")
    print(f" Validierung:           {len(result['validation_issues'])} Issues "
          f"({crit} kritisch)")
    print(f" Compliance-Status:     {comp.status} "
          f"({comp.completeness_rate * 100:.1f}% Pflichtdatenpunkte)")
    print(f" Audit-Kette gueltig:   {result['audit_valid']}")
    print("-" * 60)
    for label, path in result["outputs"].items():
        print(f" {label:12s} -> {path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
