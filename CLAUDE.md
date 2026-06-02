# CLAUDE.md — Projektkontext für Claude Code

## Was ist das?
Forschungsprototyp einer Masterarbeit (Frankfurt School, Design Science Research):
Multi-Agenten-Framework für CSRD/ESRS-E1-konformes ESG-Reporting in Finanzinstituten.
Autor: Maximilian Weiss. Abgabe ~Juli/August 2026.

## Leitprinzipien (wichtig bei jeder Änderung)
- **Evaluierbarkeit zuerst.** Jede Funktion muss gegen die Hypothesen H1 (Effizienz),
  H2 (Qualität), H3 (Adaptierbarkeit) messbar sein. Metriken in `evaluation/`.
- **MVP-Scope strikt halten:** nur ESRS E1, synthetische Daten, 5 Agenten. Die breite
  5-Schichten-Architektur (Web-Scraping, Neo4j, XBRL, Dashboards) ist *konzeptioneller*
  Thesis-Beitrag, **nicht** zu implementieren, sofern nicht ausdrücklich gewünscht.
- **Akademisch saubere Explainability:** SHAP/LIME nur auf einen echten ML-Klassifikator
  anwenden (nicht auf LLM-Freitext). Für LLM-Schritte = Quellenangabe + NL-Begründung.
- **Konfiguration statt Code:** Datenpunkte/Regeln in YAML (H3a). Keine hartkodierten Regeln.
- **Reproduzierbarkeit (QA-3.1):** deterministisches Backend muss bei gleichem Input
  identische Ergebnisse liefern. Keine Zufallszahlen ohne festen Seed.
- **DSGVO:** nur synthetische Daten, keine echten Personen-/Unternehmensdaten.
- Sprache des Codes/Docs: Deutsch (Kommentare), ASCII-sichere Strings (z. B. `tCO2e`
  statt `tCO₂e`) wegen Windows-Encoding.

## Umgebung
- Python 3.13, venv außerhalb OneDrive: `C:\Users\rweiss\esg_venv`
- Run:  `& C:\Users\rweiss\esg_venv\Scripts\python.exe main.py --eval`
- Tests: `& C:\Users\rweiss\esg_venv\Scripts\python.exe -m pytest -q`
- Repo liegt unter OneDrive — venv NICHT ins Repo legen (.gitignore).

## Schlüsseldateien
- `agents/orchestrator.py` — Workflow-Steuerung, Persistenz, Audit, PDF-Erzeugung
- `agents/*_agent.py` — Extraction / Validation / Compliance / ReportGeneration
- `agents/data_extraction_agent.py` — deterministisch + claude-Backend (LLM-Extraktion)
- `config/esrs_e1_datapoints.yaml` — Datenpunktkatalog (value_path → synth. Datenschema)
- `config/validation_rules.yaml` — Regeltypen: catalog_bounds, sum_equals, derived_equals, relation
- `evaluation/metrics.py` + `run_evaluation.py` — H2a/H2b/FA-2/H2d
- `evaluation/ml_classifier.py` — RandomForest + SHAP (H2d); Seed=42
- `data/ground_truth/*.json` — Gold Standard (Extraktion + erwartete Validierungstreffer)
- `utils/audit_logger.py` — append-only Hash-Kette (NFA-4.1)
- `utils/pdf_exporter.py` — ReportLab-PDF-Export (d)
- `utils/ingestion.py` — Schicht-2-Ingestion: JSON/CSV/Text-Multi-Source (FA-1.1/FA-1.2)
- `agents/assessment_agent.py` — Schicht-4-Assessment: KPI-Bewertung, Sektorbenchmarks, Lagebericht-Interpretation
- `ui/streamlit_app.py` — Demo-UI: Lagebericht, KPI-Assessment, SHAP-Tab, PDF-Download
- `core/llm_client.py` — Anthropic-Client (lazy init, liest ANTHROPIC_API_KEY aus .env)
- `data/benchmarks/sector_benchmarks.json` — Sektorbenchmarks fuer Assessment

## Status (Stand: Sprint 3 — vollstaendige 5-Schichten-Architektur + Lagebericht)
- Deterministischer E2E-Slice laeuft; `--eval` erfuellt alle 8 Hypothesen; 6/6 pytest gruen.
- 5-Schichten-Architektur vollstaendig implementiert (Ingestion, Extraktion, Validierung, Assessment, Report).
- ESG-Lagebericht mit KPI-Interpretation, Sektorbenchmarks, Ampelbewertung, Empfehlungen.
- H3a: 10 neue Datenpunkte via YAML (kein Code) — demonstriert NFA-3.2.
- H3b: 77.3% Wiederverwendungsrate der Agenten ueber Standards.
- (e) OFFEN: Baseline-Erhebung manueller Prozess (H1a) aus Experteninterviews
  (ausserhalb des Frameworks; Thesis-Kapitel Evaluation).

## Schluessel-Metriken (Stand Sprint 3)
- H1a Laufzeit: ~0.006 s (deterministisch, 44 DPs) vs. ~120 s (claude-Backend)
- H2a F1: 1.0 | H2b Vollstaendigkeit: 1.0 | FA-2 Erkennung: 1.0 / FP: 0.0
- H2d CV-F1: 0.853 +/- 0.058 (RandomForest+SHAP, 500 Samples, Seed=42)
- H3a: 10 neue DPs via YAML | H3b: 77.3% Wiederverwendung | H3c: YAML+Streamlit

## Konventionen
- Neue Datenpunkte/Regeln → YAML erweitern, NICHT Code. Danach `--eval` + `pytest`.
- Jede neue Agentenaktion → über `self._log(...)` in den Audit-Trail.
- Keine neuen Abhängigkeiten ohne Eintrag in `requirements.txt`.
