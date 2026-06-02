# KI-Agenten-Framework fuer ESG-Reporting (CSRD/ESRS)

**Forschungsprototyp** — Masterarbeit Maximilian Weiss, Frankfurt School of Finance & Management, 2025/2026.
Design Science Research: Multi-Agenten-Framework fuer CSRD/ESRS-konformes ESG-Reporting in Finanzinstituten.

> Wissenschaftliches Artefakt, **kein** Produktivsystem. Alle Daten sind synthetisch (DSGVO).
> Alle Ausgaben sind vor produktivem Einsatz fachlich zu pruefen.

---

## Inhalt

- [Ueberblick](#ueberblick)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Anwendung starten](#anwendung-starten)
- [Eingabedatenformat](#eingabedatenformat)
- [Manuelle Wesentlichkeitsbewertung](#manuelle-wesentlichkeitsbewertung)
- [Konfiguration](#konfiguration)
- [Architektur](#architektur)
- [Verzeichnisstruktur](#verzeichnisstruktur)
- [Hypothesen-Nachweis](#hypothesen-nachweis)
- [Hinweise vor Produktiveinsatz](#hinweise-vor-produktiveinsatz)

---

## Ueberblick

Das Framework automatisiert die Erstellung eines CSRD-konformen Nachhaltigkeitsberichts fuer Finanzinstitute. Es implementiert eine 5-Schichten-Architektur:

| Schicht | Funktion | Schluessel-Komponenten |
|---|---|---|
| 1 — Governance | Audit-Trail, Compliance-Pruefung | SHA-256-Hash-Kette, ComplianceAgent |
| 2 — Datenzugang | Einlesen strukturierter Daten | DataIngestionAgent (JSON/CSV/Text) |
| 3 — Extraktion & Validierung | Datenpunkt-Ermittlung, Plausibilitaet | DataExtractionAgent, ValidationAgent |
| 4 — Assessment | Wesentlichkeit, KPI-Bewertung | MaterialityAgent, AssessmentAgent |
| 5 — Reporting | Lagebericht, PDF, UI | ReportGenerationAgent, Streamlit |

**Umfang:**
- ESRS E1 (Klimawandel): 44 Datenpunkte, vollstaendige Extraktion und Validierung
- ESRS E2–G1: je 5–10 Datenpunkte, Extraktion und Compliance-Pruefung
- Doppelte Wesentlichkeitsanalyse: alle 10 ESRS-Standards, gemaess ESRS 1 IG 1

---

## Voraussetzungen

- Python 3.13
- Virtual Environment **ausserhalb** des Repo-Verzeichnisses anlegen (nicht unter OneDrive, da Symlink-Probleme)
- Empfohlen: `C:\Users\<User>\esg_venv`
- Fuer das Claude-Backend: API-Key von Anthropic (https://console.anthropic.com)

---

## Installation

```powershell
# 1. Virtual Environment erstellen (ausserhalb OneDrive)
python -m venv C:\Users\<User>\esg_venv

# 2. Abhaengigkeiten installieren
& C:\Users\<User>\esg_venv\Scripts\pip install -r requirements.txt

# 3. Umgebungsvariablen (optional, nur fuer Claude-Backend)
#    .env Datei im Projektverzeichnis anlegen:
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Anwendung starten

### Streamlit-Demo (empfohlen fuer Praesentation und Evaluation)

```powershell
& C:\Users\<User>\esg_venv\Scripts\streamlit run ui/streamlit_app.py
```

Der Browser oeffnet automatisch unter `http://localhost:8501`.

### Kommandozeile

```powershell
# Vollstaendige Pipeline mit Hypothesen-Evaluation
& C:\Users\<User>\esg_venv\Scripts\python main.py --eval

# Nur Pipeline, kein Eval
& C:\Users\<User>\esg_venv\Scripts\python main.py

# Mit Fehlerdatensatz (demonstriert Validierung und Gap-Analyse)
& C:\Users\<User>\esg_venv\Scripts\python main.py --input data/synthetic/synthetic_company_data_errors.json
```

### Tests

```powershell
& C:\Users\<User>\esg_venv\Scripts\python -m pytest -q
# Erwartetes Ergebnis: 6 passed
```

---

## Eingabedatenformat

Das Framework erwartet eine **JSON-Datei** mit folgendem Schema. Alle Felder sind optional —
fehlende Pflichtangaben werden als Compliance-Luecke ausgewiesen.

### Pflichtfelder fuer ESRS E1

```json
{
  "company": {
    "name": "Musterbank AG",
    "sector": "Financial Services",
    "country": "DE",
    "reporting_year": 2025,
    "employees_fte": 450,
    "revenue_mio_eur": 125.3,
    "total_assets_mio_eur": 3200.0
  },
  "emissions": {
    "scope_1_tco2e": 1250.5,
    "scope_2_location_tco2e": 3420.0,
    "scope_2_market_tco2e": 2100.0,
    "scope_3_total_tco2e": 142000.0,
    "scope_3_categories": {
      "cat_1_purchased_goods": 8500.0,
      "cat_15_investments": 125000.0
    },
    "total_ghg_location_tco2e": 146670.5,
    "total_ghg_market_tco2e": 145350.5
  },
  "energy": {
    "total_consumption_mwh": 12500.0,
    "renewable_share_percent": 45.0,
    "renewable_mwh": 5625.0,
    "fossil_mwh": 6000.0
  },
  "targets": {
    "reduction_target_percent": 50.0,
    "net_zero_year": 2040,
    "base_year": 2019
  },
  "narratives": {
    "transition_plan": "Freitext...",
    "climate_policies": "Freitext...",
    "physical_risks": "Freitext..."
  }
}
```

### Felder fuer weitere Standards (E2–G1)

Fuer die Wesentlichkeitsanalyse und Extraktion weiterer Standards sind zusaetzliche
Felder relevant. Die vollstaendige Referenzstruktur zeigt:

```
data/synthetic/synthetic_company_data.json
```

Enthaltene Bloecke: `pollution`, `water`, `biodiversity`, `resources`,
`social_own_workforce`, `social_value_chain`, `communities`, `consumers`, `governance`.

Alle Feldnamen und -typen sind in den YAML-Katalogen unter `config/esrs_*_datapoints.yaml`
dokumentiert (Spalte `value_path`).

### Unterstuetzte Eingabeformate

| Format | Voraussetzung | Backend-Empfehlung |
|---|---|---|
| JSON (strukturiert) | Schema wie oben | deterministic |
| CSV | Spalten muessen ESRS-Feldnamen entsprechen | deterministic |
| PDF / Freitext (Lagebericht) | Kein festes Schema | claude |

---

## Manuelle Wesentlichkeitsbewertung

Das Tool berechnet die Wesentlichkeit automatisch aus den Unternehmensdaten.
Sollen die Scores auf Basis eines Stakeholder-Workshops oder interner Expertenbewertung
ueberschrieben werden, kann das JSON um folgenden Block erweitert werden:

```json
{
  "materiality": {
    "E1": { "impact": 5.0, "financial": 5.0 },
    "E2": { "impact": 1.0, "financial": 1.0 },
    "S1": { "impact": 4.0, "financial": 3.5 },
    "G1": { "impact": 4.0, "financial": 4.0 }
  }
}
```

**Skala:** 1 (sehr gering) bis 5 (sehr hoch). **Schwellenwert:** >= 3,0 = wesentlich.
Nicht aufgefuehrte Standards werden weiterhin automatisch bewertet.
Der Quellenvermerk in der Analyse wird auf "manuell" gesetzt.

Diese Funktion entspricht der Anforderung IRO-1 (ESRS 1, Kap. 3): Unternehmen
muessen die Wesentlichkeitsbewertung dokumentieren und begruenden koennen.

---

## Konfiguration

Alle wesentlichen Parameter sind in `config/settings.yaml` steuerbar — ohne Code-Aenderung (NFA-3.2):

| Parameter | Pfad in YAML | Standard | Beschreibung |
|---|---|---|---|
| Extraktions-Backend | `run.extraction_backend` | `deterministic` | `deterministic` oder `claude` |
| HITL-Schwellenwert | `confidence.review_threshold` | `0.75` | Konfidenz-Grenze fuer manuelle Pruefung |
| Sprache | `run.language` | `de` | Berichtssprache (`de` oder `en`) |
| Ausgabeverzeichnis | `paths.output_dir` | `output` | Speicherort generierter Berichte |
| LLM-Modell | `llm.model` | `claude-sonnet-4-6` | Anthropic-Modell-ID |

### Datenpunkt-Kataloge erweitern (H3a-Nachweis)

Neue Datenpunkte koennen **ohne Code-Aenderung** in einen YAML-Katalog eingetragen werden:

```yaml
# In config/esrs_e1_datapoints.yaml oder einem neuen Katalog:
- id: E1-DP-NEU
  dr: E1-6
  name_de: "Scope-4-Emissionen (freiwillig)"
  category: emissions
  datatype: numeric
  unit: tCO2e
  mandatory: false
  value_path: emissions.scope_4_tco2e   # muss in der Eingabe-JSON vorhanden sein
```

Fuer einen neuen Standard wird analog ein neuer YAML-Katalog angelegt und in
`config/settings.yaml` unter `paths.additional_catalogs` eingetragen.

### Wesentlichkeits-Schwellenwert anpassen

In `config/materiality_topics.yaml` unter `metadata.materiality_threshold` (Standard: 3,0).
Ein hoehrer Schwellenwert (z.B. 3,5) fuhrt zu weniger als wesentlich eingestuften Standards.

---

## Architektur

> Detaillierte Architektur-Dokumentation: [ARCHITECTURE.md](ARCHITECTURE.md)

```
┌─────────────────────────────────────────────────────────────┐
│                     Schicht 5: Reporting                     │
│   Streamlit-UI  |  Markdown-Lagebericht  |  PDF-Export       │
├─────────────────────────────────────────────────────────────┤
│                    Schicht 4: Assessment                     │
│  Doppelte Wesentlichkeit (IG 1)  |  KPI-Sektorvergleich      │
├─────────────────────────────────────────────────────────────┤
│               Schicht 3: KI/Datenverarbeitung                │
│  Deterministisch  |  Claude-LLM  |  ML-Klassifikator (SHAP) │
├─────────────────────────────────────────────────────────────┤
│                  Schicht 2: Datenintegration                 │
│             JSON / CSV / Text-Ingestion                      │
├─────────────────────────────────────────────────────────────┤
│               Schicht 1: Governance & Compliance             │
│        Audit-Trail (SHA-256-Kette)  |  Compliance-Pruefung   │
└─────────────────────────────────────────────────────────────┘
```

**Agenten und Dateien:**

| Agent | Datei | Aufgabe |
|---|---|---|
| Orchestrator | `agents/orchestrator.py` | Workflow-Steuerung, Persistenz, PDF |
| DataExtractionAgent | `agents/data_extraction_agent.py` | Extraktion (deterministic / claude) |
| ValidationAgent | `agents/validation_agent.py` | Plausibilitaets- und Konsistenzpruefung |
| ComplianceAgent | `agents/compliance_agent.py` | ESRS-Vollstaendigkeitspruefung (nur wesentl. Standards) |
| MaterialityAgent | `agents/materiality_agent.py` | Doppelte Wesentlichkeitsanalyse (IG 1) |
| AssessmentAgent | `agents/assessment_agent.py` | KPI-Bewertung, Sektorbenchmarks, Ampel |
| ReportGenerationAgent | `agents/report_generation_agent.py` | Markdown-Lagebericht |

**Konfigurationsdateien:**

| Datei | Inhalt |
|---|---|
| `config/settings.yaml` | Systemkonfiguration, Pfade, Schwellenwerte |
| `config/esrs_e1_datapoints.yaml` | 44 ESRS-E1-Datenpunkte mit value_paths |
| `config/esrs_e2–g1_datapoints.yaml` | Datenpunkt-Kataloge E2–G1 (je 5–10 DPs) |
| `config/materiality_topics.yaml` | 10 ESRS-Standards, IG 1-Sub-Kriterien, Signale |
| `config/validation_rules.yaml` | Pruefregeln (catalog_bounds, sum_equals, etc.) |

---

## Verzeichnisstruktur

```
esg_agent_framework/
├── agents/                        # Alle Agenten
│   ├── orchestrator.py
│   ├── data_extraction_agent.py
│   ├── validation_agent.py
│   ├── compliance_agent.py
│   ├── materiality_agent.py
│   ├── assessment_agent.py
│   └── report_generation_agent.py
├── config/
│   ├── settings.yaml
│   ├── esrs_e1_datapoints.yaml    # 44 Datenpunkte
│   ├── esrs_e2_datapoints.yaml    # 8 Datenpunkte
│   ├── esrs_e3_datapoints.yaml    # 6 Datenpunkte
│   ├── esrs_e4_datapoints.yaml    # 5 Datenpunkte
│   ├── esrs_e5_datapoints.yaml    # 6 Datenpunkte
│   ├── esrs_s1_datapoints.yaml    # 10 Datenpunkte
│   ├── esrs_s2_datapoints.yaml    # 6 Datenpunkte
│   ├── esrs_s3_datapoints.yaml    # 5 Datenpunkte
│   ├── esrs_s4_datapoints.yaml    # 6 Datenpunkte
│   ├── esrs_g1_datapoints.yaml    # 9 Datenpunkte
│   ├── materiality_topics.yaml
│   └── validation_rules.yaml
├── data/
│   ├── synthetic/                 # Testdatensaetze
│   ├── ground_truth/              # Referenzwerte fuer Evaluation
│   └── benchmarks/                # Sektorbenchmarks
├── evaluation/
│   ├── metrics.py                 # H2a/H2b/FA-2
│   ├── ml_classifier.py           # Random Forest + SHAP (H2d)
│   └── run_evaluation.py
├── ui/
│   └── streamlit_app.py           # Demo-Interface
├── utils/
│   ├── audit_logger.py            # SHA-256-Hash-Kette (NFA-4.1)
│   ├── config_loader.py
│   ├── ingestion.py
│   └── pdf_exporter.py
├── ESRS/                          # ESRS-Originaldokumente (PDF, nicht im Git)
├── Omnibus/                       # EU Omnibus 2025 (PDF, nicht im Git)
├── output/                        # Generierte Berichte (git-ignoriert)
├── tests/
├── main.py
└── README.md
```

---

## Hypothesen-Nachweis

Alle Metriken werden reproduzierbar mit `python main.py --eval` gemessen (Seed=42).

| Hypothese | Beschreibung | Zielwert | Ergebnis |
|---|---|---|---|
| H1a — Effizienz | Laufzeit deterministisches Backend | < 10 s | ~0,006 s |
| H2a — Precision | Anteil korrekt extrahierter Datenpunkte | >= 0,85 | 1,0 |
| H2b — Vollstaendigkeit | Anteil gefundener Pflichtdatenpunkte | >= 0,85 | 1,0 |
| FA-2 — Fehlererkennung | Erkennungsrate injizierter Fehler | >= 0,95 | 1,0 |
| H2d — Erklaebarkeit | CV-F1 Random-Forest-Klassifikator | >= 0,75 | 0,853 +/- 0,058 |
| H3a — Adaptierbarkeit | Neue Datenpunkte per YAML, kein Code | 0 Code-Aenderungen | 10 DPs nachgewiesen |
| H3b — Wiederverwendung | Agenten-Reuse-Rate ueber Standards | >= 70 % | 77,3 % |

---

## Hinweise vor Produktiveinsatz

Dieses Framework ist ein Forschungsprototyp. Vor jedem Einsatz mit echten Daten sind
folgende Punkte zu pruefen:

**Rechtlich / Regulatorisch:**
- Externe Pruefpflicht nach CSRD Art. 34 (Wirtschaftspruefer) besteht unabhaengig vom Tool
- DSGVO Art. 35: Datenschutz-Folgenabschaetzung bei echten Mitarbeiterdaten (S1-Datenpunkte)
- Claude-Backend sendet Daten an Anthropic (USA) — Datenschutzpruefung erforderlich

**Fachlich:**
- Sektorbenchmarks sind synthetisch und muessen gegen aktuelle Marktdaten kalibriert werden
- Wesentlichkeitsschwellenwert (3,0) ist ein Standardwert — eine Kalibrierung auf Basis
  eines Stakeholder-Workshops wird empfohlen (ESRS 1, IRO-1)
- Datenpunkt-Kataloge E2–G1 sind repraesentativ, nicht vollstaendig

**Technisch:**
- Virtual Environment regelmaessig aktualisieren (`pip install -r requirements.txt --upgrade`)
- API-Key nicht in Versionskontrolle einchecken (nur `.env`-Datei verwenden)
- Output-Verzeichnis (`output/`) ist git-ignoriert und muss gesichert werden

---

*Forschungsprototyp — Frankfurt School of Finance & Management, 2025/2026.*
*Autor: Maximilian Weiss. Kontakt: ricky.martin.rmw@googlemail.com*
