# Architektur — KI-Agenten-Framework fuer ESG-Reporting

**Forschungsprototyp** — Masterarbeit Ricky Martin Weiß, Frankfurt School of Finance & Management, 2025/2026.
Design Science Research (DSR) nach Peffers et al. (2007).

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [5-Schichten-Architektur](#2-5-schichten-architektur)
3. [Agenten und ihre Verantwortlichkeiten](#3-agenten-und-ihre-verantwortlichkeiten)
4. [Datenfluesse](#4-datenfluesse)
5. [ESRS-Abdeckung](#5-esrs-abdeckung)
6. [Konfigurationsarchitektur (H3-Nachweis)](#6-konfigurationsarchitektur-h3-nachweis)
7. [Explainability-Architektur (H2d)](#7-explainability-architektur-h2d)
8. [Audit-Trail und Governance (NFA-2)](#8-audit-trail-und-governance-nfa-2)
9. [Design-Entscheidungen](#9-design-entscheidungen)

---

## 1. Ueberblick

Das Framework implementiert eine **5-Schichten-Multi-Agenten-Architektur** fuer die
(teil)automatisierte Erstellung CSRD-konformer Nachhaltigkeitsberichte. Zieldomaene:
Finanzinstitute (Sparkassen, Genossenschaftsbanken, mittelgrossere Banken).

**Kernprinzipien:**

| Prinzip | Umsetzung |
|---------|-----------|
| Konfiguration statt Code | Datenpunkte und Regeln in YAML; kein Code bei Erweiterung (H3a) |
| Reproduzierbarkeit | Deterministisches Backend: gleicher Input = identischer Output (QA-3.1) |
| Trennbarkeit | Jeder Agent hat genau eine Verantwortlichkeit (Single Responsibility) |
| Nachvollziehbarkeit | Alle Aktionen im SHA-256-verketteten Audit-Trail (NFA-2.1) |
| DSGVO | Nur synthetische Daten; LLM-Backend opt-in |

---

## 2. 5-Schichten-Architektur

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Schicht 5: Reporting                          │
│   ReportGenerationAgent  |  PDF-Export (ReportLab)  |  Streamlit-UI  │
├──────────────────────────────────────────────────────────────────────┤
│                       Schicht 4: Assessment                          │
│   MaterialityAgent (IRO-1, IG 1)  |  AssessmentAgent (KPI-Ampel)     │
├──────────────────────────────────────────────────────────────────────┤
│                    Schicht 3: KI / Datenverarbeitung                 │
│   DataExtractionAgent (deterministisch | claude)                     │
│   ValidationAgent (catalog_bounds, sum_equals, relation, ...)        │
│   ML-Klassifikator (RandomForest + SHAP, Seed=42)                    │
├──────────────────────────────────────────────────────────────────────┤
│                     Schicht 2: Datenintegration                      │
│   DataIngestionAgent (JSON / CSV / Freitext / XBRL-experimentell)    │
├──────────────────────────────────────────────────────────────────────┤
│                  Schicht 1: Governance & Compliance                  │
│   AuditLogger (SHA-256-Kette)  |  ComplianceAgent (Gap-Analyse)      │
└──────────────────────────────────────────────────────────────────────┘
                                    |
                    Orchestrator (Workflow-Steuerung)
```

Der **Orchestrator** (`agents/orchestrator.py`) ist kein eigener Layer, sondern
ein uebergeordneter Koordinations-Agent, der den Workflow sequenziell steuert
und alle Zwischenergebnisse aggregiert und persistiert.

### Ausfuehrungsreihenfolge (Orchestrator.run)

```
1. Schicht 2  — Ingestion:    DataIngestionAgent.ingest()
2. Schicht 3  — Extraktion:   DataExtractionAgent.run()
3. Schicht 3  — Validierung:  ValidationAgent.run()
4. Schicht 4  — Materialitaet: MaterialityAgent.run()   ← vor Compliance (IG 1)
5. Schicht 1  — Compliance:   ComplianceAgent.run()     ← nur wesentliche Standards
6. Schicht 4  — Assessment:   AssessmentAgent.run()
7. Schicht 5  — Report:       ReportGenerationAgent.run()
8. Schicht 5  — Persistenz:   PDF + JSON-Outputs
```

---

## 3. Agenten und ihre Verantwortlichkeiten

### BaseAgent (`agents/base.py`)

Abstrakte Basisklasse fuer alle Agenten. Stellt den gemeinsamen Audit-Zugriff
(`self._log(action, details)`) und gemeinsame Datenstrukturen bereit.

**Gemeinsame Datenstrukturen:**

| Klasse | Felder | Zweck |
|--------|--------|-------|
| `ExtractedDatapoint` | id, dr, name_de, value, present, confidence, source | Ergebnis Extraktion |
| `ValidationIssue` | check, path, severity, message, datapoint_id | Plausibilitaetsfehler |
| `ComplianceResult` | total_mandatory, present_mandatory, completeness_rate, status, gaps | Lueckenanalyse |

---

### DataIngestionAgent (`utils/ingestion.py`) — Schicht 2

Liest Eingabedaten aus verschiedenen Quellformaten und normalisiert sie auf das
interne JSON-Schema.

| Eingangsformat | Verarbeitung |
|----------------|-------------|
| JSON (strukturiert) | Direktes Laden; Schema-Validierung |
| CSV | Spalten-Mapping auf ESRS-Feldnamen |
| Freitext / PDF-Text | LLM-gestuetzte Normalisierung (claude-Backend) |
| XBRL | Experimentelles Mapping (Proof-of-Concept) |

---

### DataExtractionAgent (`agents/data_extraction_agent.py`) — Schicht 3

Extrahiert ESRS-Datenpunkte aus den eingelesenen Rohdaten. Zwei Backends:

**Deterministisches Backend** (`backend = "deterministic"`):
- Liest Werte ueber `value_path` aus dem YAML-Katalog (z.B. `emissions.scope_1_tco2e`)
- Konfidenz: 1,0 bei Treffer, 0,0 bei fehlendem Feld
- Reproduzierbar (QA-3.1), kein API-Aufruf, ~0,006 s Laufzeit
- Baseline-Backend fuer Hypothesen-Evaluation

**Claude-Backend** (`backend = "claude"`):
- Serialisiert Unternehmensdaten als strukturierten Berichtstext (`_company_to_text`)
- Sendet Batch-Prompts an Claude Sonnet 4.6 (~34 API-Calls)
- Gibt Konfidenzwerte 0,0–1,0 zurueck; Werte unterhalb `review_threshold` (Standard: 0,75) werden fuer Human-in-the-Loop markiert
- Gegenstand von Hypothese H2a

---

### ValidationAgent (`agents/validation_agent.py`) — Schicht 3

Prueft extrahierte Datenpunkte gegen konfigurierte Regeln in `config/validation_rules.yaml`.

**Regeltypen:**

| Typ | Beispiel | Beschreibung |
|-----|---------|-------------|
| `non_negative` | scope_1 >= 0 | Wertebereich-Pruefung |
| `range` | renewable_share in [0, 100] | Min/Max-Grenzen |
| `sum_equals` | scope_1 + scope_2 + scope_3 = total | Aggregationskonsistenz |
| `relation` | scope_2_market <= scope_2_location | Relationsregel |
| `derived_equals` | renewable_mwh = total * share / 100 | Berechnungspruefung |
| `catalog_bounds` | Wert im YAML definierten Bereich | Katalogbasierte Grenzen |

Alle Regeln sind YAML-konfigurierbar (kein Code bei neuen Regeln, NFA-3.2).

---

### MaterialityAgent (`agents/materiality_agent.py`) — Schicht 4

Fuehrt die **doppelte Wesentlichkeitsanalyse** gemaess ESRS 1 Kap. 3 / IG 1 durch.

**Zwei Dimensionen pro Standard:**

| Dimension | Sub-Kriterien (IG 1) | Beschreibung |
|-----------|---------------------|-------------|
| Impact-Wesentlichkeit | Scale, Scope, Irremediability, Likelihood | Auswirkungen des Unternehmens auf Gesellschaft/Umwelt |
| Financial-Wesentlichkeit | — | Finanzielle Auswirkungen auf das Unternehmen |

Der Score (1–5) wird heuristisch aus den Unternehmensdaten berechnet oder
kann manuell ueberschrieben werden (Stakeholder-Workshop, IRO-1-Anforderung).
Schwellenwert: >= 3,0 = wesentlich (konfigurierbar in `materiality_topics.yaml`).

**Wichtig:** MaterialityAgent laueft vor ComplianceAgent, damit nur wesentliche Standards
auf Vollstaendigkeit geprueft werden (IG 1: Proportionalitaetsprinzip).

---

### ComplianceAgent (`agents/compliance_agent.py`) — Schicht 1

Prueft, ob alle Pflichtdatenpunkte wesentlicher Standards vorhanden sind.

- Filtert auf `material_standards` aus dem MaterialityAgent
- Berechnet `completeness_rate` = vorhanden / gesamt (Pflicht)
- Ampelbewertung: GRUEN (>= 90 %), GELB (>= 70 %), ROT (< 70 %)
- Gibt konkrete Lueckenliste (`gaps`) fuer den Bericht zurueck

---

### AssessmentAgent (`agents/assessment_agent.py`) — Schicht 4

Bewertet KPIs gegen Sektorbenchmarks (`data/benchmarks/sector_benchmarks.json`).

- Ampel-Bewertung (GRUEN / GELB / ROT) pro KPI
- Abweichungsberechnung vs. Sektor-Median und Perzentile (p10–p90)
- Automatische Interpretationstexte (deterministisch aus Benchmark-Daten)
- Abdeckung: E1, S1, S2 mit repraessentativen Benchmarks

---

### ReportGenerationAgent (`agents/report_generation_agent.py`) — Schicht 5

Erstellt den Markdown-Lagebericht auf Basis aller Vorschicht-Ergebnisse.

- Template-basiert (`config/report_template.md`)
- Abschnitte: Unternehmensueberblick, Wesentlichkeit, E1-Bericht, weitere Standards,
  Validierungsergebnisse, Compliance-Status, KPI-Assessment, Empfehlungen
- Executive Summary: deterministisch (aus Benchmark-Daten) oder via LLM (claude-Backend)
- Ausgabe: Markdown + PDF (via `utils/pdf_exporter.py`, ReportLab)

---

### Orchestrator (`agents/orchestrator.py`)

Koordiniert den gesamten Workflow, verwaltet den Audit-Trail und persistiert Ergebnisse.

**Outputs pro Lauf:**

| Datei | Inhalt |
|-------|--------|
| `output/report_<datum>.md` | Markdown-Lagebericht |
| `output/report_<datum>.pdf` | PDF-Export |
| `output/extraction_results_<datum>.json` | Alle extrahierten Datenpunkte |
| `output/validation_results_<datum>.json` | Alle Validierungsprobleme |
| `output/assessment_results_<datum>.json` | KPI-Bewertungen |
| `output/audit_log_<datum>.json` | SHA-256-verketteter Audit-Trail |
| `output/evaluation_results.json` | Hypothesen-Metriken (nur mit --eval) |

---

## 4. Datenfluesse

```
Eingabe (JSON/CSV/Text)
        |
        v
[DataIngestionAgent]  ──────────────────── Schicht 2
   company_data: dict
        |
        v
[DataExtractionAgent]  ─────────────────── Schicht 3
   extracted: list[ExtractedDatapoint]
        |
        +──────────> [ValidationAgent]
        |              issues: list[ValidationIssue]
        |
        v
[MaterialityAgent]  ────────────────────── Schicht 4
   materiality: MaterialityResult
   material_standards: list[str]
        |
        v
[ComplianceAgent(material_standards)]  ─── Schicht 1
   compliance: ComplianceResult
        |
        v
[AssessmentAgent(company_data, extracted, compliance)]  ── Schicht 4
   assessment: AssessmentResult
        |
        v
[ReportGenerationAgent]  ───────────────── Schicht 5
   report_md: str
        |
        v
[PDF-Export + JSON-Persistenz]
```

Alle Agenten schreiben ihre Aktionen in den gemeinsamen `AuditLogger` (Schicht 1).

---

## 5. ESRS-Abdeckung

Das Framework konfiguriert alle 10 CSRD-ESRS-Standards. Prototyp-Fokus liegt auf E1.

| Standard | Thema | Datenpunkte | Extraktion | Validierung | Ground Truth |
|----------|-------|------------|-----------|------------|-------------|
| **E1** | Klimawandel | **44** | deterministisch + claude | vollstaendig (6 Regeltypen) | vorhanden |
| E2 | Umweltverschmutzung | 8 | deterministisch | — | — |
| E3 | Wasser & Meeresressourcen | 6 | deterministisch | — | — |
| E4 | Biodiversitaet | 5 | deterministisch | — | — |
| E5 | Ressourcennutzung | 6 | deterministisch | — | — |
| S1 | Eigene Belegschaft | 10 | deterministisch | — | — |
| S2 | Wertschoepfungskette | 6 | deterministisch | — | — |
| S3 | Betroffene Gemeinschaften | 5 | deterministisch | — | — |
| S4 | Verbraucher & Endnutzer | 6 | deterministisch | — | — |
| G1 | Unternehmensfuehrung | 9 | deterministisch | — | — |
| **Gesamt** | | **105** | | | |

**Abgrenzung:** E2–G1 demonstrieren die YAML-Erweiterbarkeit (H3a). Die vollstaendige
Extraktion, Validierung und Ground Truth ist bewusst auf E1 beschraenkt (vertikaler
Prototyp-Scope gemaess DSR-Methodologie).

**Doppelte Wesentlichkeit:** Alle 10 Standards vollstaendig in
`config/materiality_topics.yaml` mit IG 1-konformen Sub-Kriterien (Scale, Scope,
Irremediability, Likelihood, Financial).

---

## 6. Konfigurationsarchitektur (H3-Nachweis)

Alle Datenpunkte und Regeln sind in YAML konfiguriert — **kein Code** bei Erweiterung.

### Datenpunkt-Katalog-Schema (H3a)

```yaml
# config/esrs_e1_datapoints.yaml (Auszug)
metadata:
  standard: "ESRS E1"
  version: "2023"
  source: "EU 2023/2772, Anhang I"

datapoints:
  - id: E1-DP-001
    dr: E1-6          # Disclosure Requirement
    name_de: "Scope-1-THG-Emissionen"
    category: emissions
    datatype: numeric
    unit: tCO2e
    mandatory: true
    value_path: emissions.scope_1_tco2e   # Pfad im Eingabe-JSON
```

Neuer Datenpunkt = ein YAML-Eintrag, kein Python-Code (H3a-Nachweis: 10 neue DPs
ohne Code-Aenderung demonstriert).

### Wesentlichkeitskonfiguration

```yaml
# config/materiality_topics.yaml (Auszug)
metadata:
  materiality_threshold: 3.0    # Schwellenwert konfigurierbar

topics:
  - standard: "ESRS E1"
    impact_signals:             # Heuristiken fuer automatische Bewertung
      - path: emissions.scope_1_tco2e
        threshold: 1000
        score_contribution: 1.0
```

### Konfigurationshierarchie

```
config/settings.yaml              ← System-Parameter, Pfade, Schwellenwerte
config/esrs_*_datapoints.yaml     ← Datenpunkt-Kataloge (10 Dateien)
config/materiality_topics.yaml    ← Wesentlichkeitslogik (alle Standards)
config/validation_rules.yaml      ← Plausibilitaetsregeln
config/report_template.md         ← Berichtsvorlage
```

---

## 7. Explainability-Architektur (H2d)

Das Framework unterscheidet zwei Explainability-Ebenen:

### LLM-Schritte (claude-Backend)

- **Quellenangabe:** Jeder extrahierte Datenpunkt enthaelt `source.method = "claude"`,
  `source.prompt_excerpt` und `source.confidence`
- **NL-Begruendung:** Assessment-Texte und Executive Summary sind in natuerlicher Sprache
- Kein SHAP/LIME auf LLM-Freitext (methodisch nicht sinnvoll)

### ML-Klassifikator (H2d — `evaluation/ml_classifier.py`)

Random-Forest-Klassifikator auf 10 quantitativen ESRS-E1-Merkmalen:

| Merkmal | Beschreibung |
|---------|-------------|
| scope_1_tco2e | Direkte Emissionen |
| scope_2_tco2e | Energiebezogene Emissionen |
| scope_3_tco2e | Indirekte Emissionen (Lieferkette) |
| total_ghg_tco2e | Gesamtemissionen |
| renewable_share_pct | Erneuerbare-Energien-Anteil |
| reduction_target_pct | Reduktionsziel |
| energy_intensity | Energieintensitaet |
| ghg_intensity | THG-Intensitaet |
| physical_risk_exposure | Physisches Klimarisikoexposure |
| years_to_net_zero | Verbleibende Jahre bis Netto-Null |

**Design-Entscheidungen:**
- `random_state=42` — vollstaendig reproduzierbar (QA-3.1)
- `class_weight='balanced'` — gleicht Klassenverteilung aus (65 % valide / 35 % fehlerhaft)
- 5-Fold-Cross-Validation → CV-F1 = 0,853 ± 0,058
- **SHAP** (Shapley Additive Explanations) fuer unverzerrte Feature-Wichtigkeit

---

## 8. Audit-Trail und Governance (NFA-2)

`utils/audit_logger.py` implementiert einen append-only, SHA-256-verketteten Audit-Trail:

```
Eintrag N:
  agent:     "DataExtractionAgent"
  action:    "extraction_completed"
  timestamp: "2025-06-01T10:30:00Z"
  details:   {"datapoints_total": 105, "datapoints_present": 44}
  prev_hash: SHA-256(Eintrag N-1)
  this_hash: SHA-256(alle Felder + prev_hash)
```

- `AuditLogger.verify()` prueft die gesamte Hash-Kette auf Intaktheit
- Alle Agenten schreiben ueber `self._log(action, details)` in denselben Trail
- Ergebnis: manipulationssicheres Protokoll (NFA-2.1)

---

## 9. Design-Entscheidungen

### Warum Multi-Agenten statt Monolith?

| Aspekt | Monolith | Multi-Agenten-Framework |
|--------|----------|------------------------|
| Wiederverwendbarkeit | gering | hoch (H3b: 66,7 % Voll-Reuse-Rate) |
| Erweiterbarkeit | Eingriff in Kerncode | Neuer Agent ohne Aenderung bestehender Agenten |
| Testbarkeit | schwer zu isolieren | Jeder Agent einzeln testbar |
| Nachvollziehbarkeit | Black Box | Audit-Trail pro Agent-Aktion |

### Warum deterministisches Backend als Baseline?

- Reproduzierbarkeit (QA-3.1) fuer akademische Evaluation unverzichtbar
- F1 = 1,0 beweist, dass das YAML-Schema vollstaendig ist
- Laufzeit ~0,006 s erlaubt H1a-Nachweis ohne Benchmark-Messungenauigkeit

### Warum YAML statt Datenbank?

- Versionierbar (Git-Diff zeigt genau welcher Datenpunkt geaendert wurde)
- Kein Datenbankserver erforderlich (Deployment-Einfachheit)
- Menschenlesbar (Gutachter kann Katalog direkt pruefen)
- H3a-Nachweis: Erweiterung ohne Programmierkenntnis moeglich

### Prototyp-Scope-Abgrenzung

Konzeptionelle Thesis-Beitraege, die **nicht** implementiert sind:
- Web-Scraping und automatische Quellenerfassung
- Neo4j-Graph-Datenbank fuer Unternehmensbeziehungen
- XBRL-vollstaendiger Export (nur experimentelles Proof-of-Concept)
- Echtzeit-Dashboards und Alerting

Diese Abgrenzung folgt der DSR-Methodologie: der Prototyp validiert
die Kernhypothesen H1–H3, nicht den vollstaendigen Produktivbetrieb.

---

*Forschungsprototyp — Frankfurt School of Finance & Management, 2025/2026.*
*Autor: Ricky Martin Weiß. Kontakt: ricky.martin.rmw@googlemail.com*
