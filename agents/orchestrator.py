"""Orchestrator (UC-01 / FA-5.1).

Zentraler Koordinations-Agent: implementiert die 5-Schichten-Architektur der Thesis
(Weiss et al., 2025) fuer CSRD/ESRS-konformes ESG-Reporting (alle Standards E1-G1).

Workflow: Ingestion (Schicht 2) -> Extraktion (Schicht 3) -> Validierung (Schicht 3)
          -> Compliance (Schicht 1) -> Materialitaet (Schicht 4) -> Assessment (Schicht 4)
          -> Report (Schicht 5)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from agents.assessment_agent import AssessmentAgent
from agents.compliance_agent import ComplianceAgent
from agents.data_extraction_agent import DataExtractionAgent
from agents.materiality_agent import MaterialityAgent
from agents.report_generation_agent import ReportGenerationAgent
from agents.validation_agent import ValidationAgent
from core.llm_client import ClaudeClient
from utils.audit_logger import AuditLogger
from utils.config_loader import load_json, load_settings, load_yaml, resolve, save_json
from utils.ingestion import DataIngestionAgent
from utils.pdf_exporter import build_pdf_bytes


class Orchestrator:
    name = "Orchestrator"

    def __init__(self, settings_path: str = "config/settings.yaml") -> None:
        self.settings = load_settings(settings_path)
        self.catalog = self._load_all_catalogs()
        self.rules = load_yaml(self.settings["paths"]["validation_rules"])
        with open(resolve(self.settings["paths"]["report_template"]), "r", encoding="utf-8") as fh:
            self.template = fh.read()
        self.audit = AuditLogger()

    def _load_all_catalogs(self) -> dict:
        """Laedt alle konfigurierten ESRS-Datenpunkt-Kataloge und fuegt sie zusammen."""
        primary = load_yaml(self.settings["paths"]["datapoint_catalog"])
        all_dps = list(primary.get("datapoints", []))
        catalogs_meta = [{"standard": primary["metadata"]["standard"],
                          "catalog": primary}]
        for path in self.settings["paths"].get("additional_catalogs", []):
            cat = load_yaml(path)
            all_dps.extend(cat.get("datapoints", []))
            catalogs_meta.append({"standard": cat["metadata"]["standard"],
                                   "catalog": cat})
        merged = dict(primary)
        merged["datapoints"] = all_dps
        merged["_catalogs"] = catalogs_meta
        return merged

    def _maybe_llm(self):
        if self.settings["run"]["extraction_backend"] != "claude":
            return None
        llm_cfg = self.settings.get("llm", {})
        return ClaudeClient(
            model=llm_cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=llm_cfg.get("max_tokens", 2000),
            temperature=llm_cfg.get("temperature", 0.2),
        )

    def run(self, input_path: str, output_dir: str | None = None,
            source_type: str = "auto", progress_callback=None) -> dict:
        def _step(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        start = time.perf_counter()
        backend = self.settings["run"]["extraction_backend"]
        review_threshold = self.settings.get("confidence", {}).get("review_threshold", 0.75)
        language = self.settings["run"].get("language", "de")
        out_dir = Path(resolve(output_dir or self.settings["paths"]["output_dir"]))

        self.audit.log(self.name, "workflow_started",
                       {"input": input_path, "backend": backend, "source_type": source_type})

        # -- Schicht 2: Ingestion ----------------------------------------------
        _step("Schicht 2 — DataIngestionAgent: Eingabedaten einlesen und normalisieren ...")
        llm = self._maybe_llm()
        ingestion_agent = DataIngestionAgent(llm=llm)
        company_data = ingestion_agent.ingest(input_path, source_type=source_type)
        source_name = Path(input_path).name
        self.audit.log(self.name, "ingestion_completed",
                       {"source": source_name, "type": source_type})

        # -- Schicht 3: Extraktion --------------------------------------------
        n_dps = len(self.catalog.get("datapoints", []))
        _step(f"Schicht 3 — DataExtractionAgent: {n_dps} ESRS-Datenpunkte extrahieren"
              f" (Backend: {backend}) ...")
        extraction = DataExtractionAgent(
            self.audit, self.catalog, backend, review_threshold, llm
        )
        extracted = extraction.run(company_data, source_name)

        # -- Schicht 3: Validierung -------------------------------------------
        _step("Schicht 3 — ValidationAgent: Plausibilitaets- und Konsistenzpruefung ...")
        validator = ValidationAgent(self.audit, self.catalog, self.rules)
        issues = validator.run(company_data)

        # -- Schicht 4: Doppelte Wesentlichkeitsanalyse (IRO-1) ---------------
        _step("Schicht 4 — MaterialityAgent: Doppelte Wesentlichkeitsanalyse (ESRS 1, IRO-1) ...")
        materiality_agent = MaterialityAgent(self.audit)
        materiality = materiality_agent.run(company_data)
        material_standards = materiality.wesentliche_themen

        # -- Schicht 1: Compliance / Gap-Analyse ------------------------------
        _step(f"Schicht 1 — ComplianceAgent: Vollstaendigkeitspruefung fuer "
              f"{len(material_standards)} wesentliche Standards ...")
        compliance_agent = ComplianceAgent(
            self.audit, self.catalog, material_standards=material_standards
        )
        compliance = compliance_agent.run(extracted)

        # -- Schicht 4: Assessment & Interpretation ---------------------------
        _step("Schicht 4 — AssessmentAgent: KPI-Bewertung und Sektorvergleich ...")
        assessment_agent = AssessmentAgent(self.audit, llm=llm)
        assessment = assessment_agent.run(company_data, extracted, compliance)

        # -- Schicht 5: Report-Generierung ------------------------------------
        _step("Schicht 5 — ReportGenerationAgent: Lagebericht erstellen ...")
        reporter = ReportGenerationAgent(
            self.audit, self.template, language, backend, llm
        )
        report_md = reporter.run(company_data, extracted, issues, compliance,
                                 assessment, materiality)

        elapsed = round(time.perf_counter() - start, 3)
        self.audit.log(self.name, "workflow_completed",
                       {"elapsed_seconds": elapsed, "chain_valid": self.audit.verify()})

        # -- PDF --------------------------------------------------------------
        _step("PDF-Export und Persistenz ...")
        pdf_bytes = build_pdf_bytes(
            company_data, extracted, issues, compliance,
            report_md, elapsed, backend,
            assessment=assessment, materiality=materiality,
        )

        outputs = self._persist(
            out_dir, report_md, pdf_bytes, extracted, issues,
            compliance, assessment, materiality, source_name, elapsed
        )

        return {
            "extracted": extracted,
            "validation_issues": issues,
            "compliance": compliance,
            "materiality": materiality,
            "assessment": assessment,
            "report_markdown": report_md,
            "report_pdf": pdf_bytes,
            "elapsed_seconds": elapsed,
            "audit_valid": self.audit.verify(),
            "outputs": outputs,
        }

    def _persist(self, out_dir: Path, report_md: str, pdf_bytes: bytes,
                 extracted, issues, compliance, assessment, materiality,
                 source_name: str, elapsed: float) -> dict:
        reports = out_dir / "reports"
        logs = out_dir / "audit_logs"
        reports.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        report_path = reports / f"esrs_report_{stamp}.md"
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(report_md)

        pdf_path = reports / f"esrs_report_{stamp}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        validation_path = reports / f"validation_report_{stamp}.json"
        save_json(validation_path, {
            "source": source_name,
            "issue_count": len(issues),
            "issues": [i.to_dict() for i in issues],
        })

        compliance_path = reports / f"compliance_report_{stamp}.json"
        save_json(compliance_path, compliance.to_dict())

        extraction_path = reports / f"extraction_{stamp}.json"
        save_json(extraction_path, {
            "source": source_name,
            "elapsed_seconds": elapsed,
            "datapoints": [e.to_dict() for e in extracted],
        })

        assessment_path = reports / f"assessment_{stamp}.json"
        if assessment is not None:
            save_json(assessment_path, assessment.to_dict())

        materiality_path = reports / f"materiality_{stamp}.json"
        if materiality is not None:
            save_json(materiality_path, materiality.to_dict())

        audit_path = logs / f"audit_trail_{stamp}.json"
        self.audit.export(audit_path)

        return {
            "report": str(report_path),
            "report_pdf": str(pdf_path),
            "validation": str(validation_path),
            "compliance": str(compliance_path),
            "extraction": str(extraction_path),
            "assessment": str(assessment_path),
            "materiality": str(materiality_path),
            "audit_trail": str(audit_path),
        }
