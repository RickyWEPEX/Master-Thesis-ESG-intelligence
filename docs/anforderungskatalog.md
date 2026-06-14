# Anforderungskatalog — KI-Agenten-Framework für ESG-Berichterstattung

**Masterarbeit Ricky Martin Weiß · Frankfurt School of Finance & Management · 2026**

**Zweck.** Dieser Katalog ist die *einzige maßgebliche Quelle* (Single Source of Truth) für sämtliche
Anforderungs-IDs des Frameworks. Er löst die in Kapitel 4 referenzierte Zusage „die detaillierte
Zuordnung findet sich im Anforderungsdokument im Anhang" ein und stellt sicher, dass Thesis-Fließtext,
Code-Kommentare und Tests dieselbe Nummerierung verwenden.

**Kanonik-Regel.** Maßgeblich sind die in Abschnitt 4.2 der Thesis eingeführten Top-Level-Anforderungen
(FA-1…FA-5, NFA-1…NFA-5) sowie die sechs Design Principles (DP-1…DP-6, Abschnitt 4.1.3). Die im Repository
verwendeten Sub-IDs wurden gegen dieses Schema abgeglichen; abweichend vergebene IDs wurden in die korrekte
Anforderungsfamilie überführt (siehe Abschnitt 6, *Migrationstabelle*).

**Legende.**
Priorität: **M** = Muss · **S** = Soll · **K** = Kann.
Status: **[x] erfüllt** (empirisch nachgewiesen) · **[~] teilweise** (umgesetzt, Zielkriterium nicht im Zielumfang gemessen) · **[ ] Roadmap** (konzeptionell vorgesehen, nicht implementiert).

---

## 1. Funktionale Anforderungen (FA)

### FA-1 — Datenidentifikation und -extraktion
Automatisierte Identifikation und Extraktion ESRS-relevanter Datenpunkte aus strukturierten Quellen
(ERP, Datenbanken) und unstrukturierten Dokumenten (NLP); konfigurierbar über ESRS-Datenpunktkataloge;
Quellenherkunft je Datenpunkt dokumentiert.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| FA-1 | Extraktion ESRS-relevanter Datenpunkte | Recall ≥ 0,85 **und** Precision ≥ 0,85 | `DataExtractionAgent` | F1 = 1,0 (P = 1,0 / R = 1,0) auf Gold-Standard (34 produktive E1-DP) | M | [x] |
| FA-1.1 | Strukturierte Quellen (JSON/CSV) normalisiert einlesen | Multi-Source-Ingestion ohne Datenverlust | `DataIngestionAgent` (`utils/ingestion.py`) | Szenario A/B reproduzierbar verarbeitet | M | [x] |
| FA-1.2 | Unstrukturierte Quellen via LLM (Claude-Backend) | Extraktion mit Konfidenzwert je DP | `DataExtractionAgent` (`llm_extraction`) | Backend integriert; auf synth. Daten evaluiert | S | [~] |
| FA-1.3 | Extraktion über YAML-Kataloge konfigurierbar | Neue DP ohne Code-Änderung | `config/esrs_*_datapoints.yaml` | 105 DP über 10 Kataloge | M | [x] |
| FA-1.4 | Quellenherkunft je Datenpunkt dokumentiert | `source`-Feld (Datei, value_path, Methode) | `ExtractedDatapoint.source` | je Extraktion gesetzt | M | [x] |

### FA-2 — Datenvalidierung und Qualitätssicherung
Validierung gegen ESRS-Definitionen und Datentypen, Plausibilitäts- und Konsistenzprüfungen
(inkl. Cross-Standard), Lückenidentifikation mit priorisierten Hinweisen.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| FA-2 | Erkennung von Validierungsfehlern | ≥ 95 % erkannt **bei** False-Positive-Rate ≤ 10 % | `ValidationAgent`, `config/validation_rules.yaml` | Erkennung 1,0 / FP-Rate 0,0 (Szenario B) | M | [x] |
| FA-2.1 | Typ-/Wertebereichsprüfung (`catalog_bounds`, `range`, `non_negative`) | Verstöße erkannt und klassifiziert | `ValidationAgent` | in 26 Regeln abgedeckt | M | [x] |
| FA-2.2 | Plausibilität (`sum_equals`, `derived_equals`, `relation`) | Summen-/Ableitungsregeln geprüft | `ValidationAgent` | in 26 Regeln abgedeckt | M | [x] |
| FA-2.3 | Cross-Standard-Konsistenz | standardübergreifende Beziehungen prüfbar | `validation_rules.yaml` (E1,E2,E3,E5,G1,S1,S2) | Regeln über 7 Standards aktiv | S | [x] |

### FA-3 — Compliance-Prüfung
Vollständigkeitsprüfung gemäß ESRS, Unterscheidung verpflichtender/freiwilliger Angaben, Compliance-Bericht
mit Ampel-Logik.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| FA-3 | Vollständigkeits-/Compliance-Prüfung | ≥ 95 % der Compliance-Verstöße erkannt | `ComplianceAgent` | Gap-Recall 1,0; fehlende Pflichtangabe (E1-DP-030) erkannt | M | [x] |
| FA-3.1 | Gap-Analyse: fehlende Pflichtangaben mit Handlungsempfehlung | priorisierte Lückenliste je wesentlichem Standard | `ComplianceAgent` | 51/51 Pflicht-DP geprüft, Ampel GRÜN | M | [x] |

### FA-4 — Wesentlichkeitsanalyse
Doppelte Wesentlichkeitsanalyse gemäß ESRS 1 / EFRAG IG 1 über Scale, Scope, Irremediability, Likelihood;
manuelle Eingaben und automatische Heuristiken.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| FA-4 | Doppelte Wesentlichkeitsanalyse (Impact + Financial) | ≥ 80 % Übereinstimmung mit Experteneinschätzung | `MaterialityAgent`, `config/materiality_topics.yaml` | funktional umgesetzt (8/10 Standards material); **quantitative Experten-Übereinstimmung nicht erhoben** | M | [~] |

> **Integritätshinweis:** Das Akzeptanzkriterium „≥ 80 % Übereinstimmung mit Experteneinschätzung"
> wurde im Rahmen der Evaluation **nicht als Metrik erhoben** (die Experten führten den
> H3c-Konfigurationstest und die H2d-Likert-Bewertung durch, keinen Wesentlichkeits-Abgleich). FA-4 ist
> daher funktional erfüllt, das numerische Akzeptanzkriterium jedoch offen — in Kapitel 7 (Limitationen) so auszuweisen.

### FA-5 — Berichtserstellung
Strukturierte, Template-basierte Berichte in mehreren Formaten; enthalten alle verpflichtenden
ESRS-Offenlegungen; klare Trennung wesentlicher/nicht-wesentlicher Themen.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| FA-5 | Template-basierte Berichtsgenerierung | vollständige Offenlegung wesentlicher Themen | `ReportGenerationAgent`, `config/report_template.md` | Lagebericht generiert | M | [x] |
| FA-5.1 | Orchestrierte End-to-End-Berichtserstellung | siebenstufiger Workflow bis Lagebericht | `Orchestrator` | Pipeline durchläuft Testdatensatz | M | [x] |
| FA-5.2 | Multi-Format-Ausgabe (Markdown, PDF, JSON) | Bericht in allen drei Formaten exportierbar | `ReportGenerationAgent`, `utils/pdf_exporter.py` | MD/PDF/JSON erzeugt | M | [x] |
| FA-5.3 | Konfigurierbarer Human-in-the-Loop-Review *(Querverweis NFA-1.2)* | Schwellenwert (Default 0,75) steuerbar | `config/settings.yaml` (`review_threshold`) | DP < Schwelle in Review-Queue | S | [x] |
| FA-5.4 | LLM-gestützte Narrative mit Quellenbindung | generierte Begründung (`reasoning`) je Aussage | `ReportGenerationAgent`, `core/llm_client.py` | LLM-Narrative integriert | S | [~] |
| FA-5.5 | Dokumentation von Datenherkunft und Generierungslogik im Bericht | Provenienz im Output ausgewiesen | `ReportGenerationAgent` | Quellen-/Methodenangabe im Bericht | S | [x] |
| FA-5.6 | Maschinenlesbarer ESEF/XBRL-Export gemäß ESEF-Taxonomie | valider (i)XBRL-Output | `utils/ingestion.py` (XBRL experimentell), Roadmap | XBRL-Parser experimentell; Export nicht produktiv | K | [ ] |

---

## 2. Nicht-funktionale Anforderungen (NFA)

### NFA-1 — Erklärbarkeit und Transparenz
Nachvollziehbare Dokumentation aller KI-Entscheidungen (Modelle, Eingaben, Konfidenzen); für Nicht-Experten
verständliche Begründungen; SHAP-basierte Erklärungen für KPI-Bewertungen.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| NFA-1 | Erklärbarkeit aller KI-Entscheidungen | Modelle, Eingaben, Konfidenzen dokumentiert | `DataExtractionAgent`, `ml_classifier.py` | Konfidenz je Extraktion; H2d Likert-Median 4 | M | [x] |
| NFA-1.1 | Quellenangabe je Datenpunkt | Herkunft nachvollziehbar | `ExtractedDatapoint.source` | gesetzt | M | [x] |
| NFA-1.2 | Konfidenzbasierte Kennzeichnung zur Prüfung | Schwellenwert konfigurierbar | `config/settings.yaml` | Review-Queue aktiv | M | [x] |
| NFA-1.3 | Begründungstexte für generierte/abgeleitete Inhalte | `reasoning` je LLM-Ausgabe | `core/llm_client.py` | LLM-Begründung mitgeliefert | S | [~] |
| NFA-1.4 | SHAP-basierte Erklärung der ML-Bewertung | mittlere abs. SHAP-Werte vs. Gini | `evaluation/ml_classifier.py` | bit-exakt reproduzierbar (Seed 42) | M | [x] |

### NFA-2 — Prüfungsfähigkeit *(setzt DP-6 um)*
Vollständiger, mittels SHA-256 manipulationssicherer Audit-Trail aller Verarbeitungsschritte
(Zeitstempel, Agent, Aktion, Ein-/Ausgaben, Konfidenz); Integrität durch Neuberechnung verifizierbar;
exportierbar.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| NFA-2 | Manipulationssicherer Audit-Trail | jeder Schritt protokolliert, integritätsgeprüft | `utils/audit_logger.py` | Audit-Kette gültig (`chain_valid`) | M | [x] |
| NFA-2.1 | Lückenlose append-only SHA-256-Hash-Kette | jeder Agentenschritt unveränderlich verkettet | `AuditLogger.log()` | Genesis-Block + Vorgänger-Hash je Eintrag | M | [x] |
| NFA-2.2 | Integritätsverifikation durch Hash-Neuberechnung | Manipulation deterministisch erkannt | `AuditLogger.verify()` | Testfall 1 (Manipulation erkannt) | M | [x] |
| NFA-2.3 | Exportierbarkeit des Audit-Trails | JSON-Export inkl. `chain_valid`-Flag | `AuditLogger.export()` | Audit-Logs persistiert | S | [x] |

### NFA-3 — Konfigurierbarkeit und Wartbarkeit
Anpassbarkeit über deklarative YAML-Dateien; neue Datenpunkte und Regeln ohne Programmiereingriffe.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| NFA-3 | YAML-basierte Konfigurierbarkeit ohne Code | neue DP/Regeln rein deklarativ | `config/*.yaml` | 10 neue DP via YAML (H3a) | M | [x] |
| NFA-3.1 | Austauschbares LLM-/Backend ohne Code | Modell/Backend per Parameter wählbar | `config/settings.yaml` (`llm.model`, `extraction_backend`) | konfigurierbar | S | [x] |
| NFA-3.2 | Erweiterbare Validierungsregeln ohne Code | Regeln in `validation_rules.yaml` | `ValidationAgent` | 26 Regeln deklarativ | M | [x] |

> **Agenten-Wiederverwendung (H3b):** 4 von 6 Kern-Agenten (Extraction, Compliance, Materiality, Report)
> werden ohne jede Konfiguration standardübergreifend wiederverwendet (= **66,7 %** Voll-Reuse). Validation und
> Assessment sind ebenfalls standardübergreifend, erfordern jedoch standardspezifische YAML-Einträge.

### NFA-4 — Skalierbarkeit und Performance
Verarbeitung von Berichten mit bis zu 10.000 Datenpunkten innerhalb von 30 Minuten; horizontal skalierbar.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| NFA-4 | Verarbeitung großer Berichtsvolumina | ≤ 30 min für 10.000 DP | `Orchestrator` (sequenzielle Pipeline) | 105 DP in ~0,1 s; **nicht bei Zielvolumen 10.000 gemessen** | S | [~] |

> **Integritätshinweis:** Das Zielkriterium (10.000 DP / 30 min) ist eine Design-Vorgabe; gemessen wurde
> die Pipeline am Prototyp-Umfang (105 DP). Eine Skalierungsmessung bei Zielvolumen steht aus (Kapitel 7).

### NFA-5 — Sicherheit und Datenschutz
Verschlüsselte Speicherung/Übertragung, rollenbasierte Zugriffskontrolle, DSGVO-Konformität.

| ID | Anforderung | Akzeptanzkriterium | Umsetzende Komponente | Evidenz | Prio | Status |
|----|-------------|--------------------|-----------------------|---------|------|--------|
| NFA-5 | Datenschutz und Zugriffssicherheit | Verschlüsselung, RBAC, DSGVO | nur synthetische Daten; `core/llm_client.py` (kein Hardcoded-Key) | per Design DSGVO-konform (keine Echtdaten); RBAC/Verschlüsselung nicht implementiert | M | [~] |

> **Integritätshinweis:** Der Prototyp arbeitet ausschließlich mit synthetischen Daten; Verschlüsselung und
> rollenbasierte Zugriffskontrolle sind als Roadmap (Phase 2/3) vorgesehen, nicht implementiert.
>
> **Abgrenzung:** Die maschinenlesbare ESEF/XBRL-Berichterstattung (vormals im Repo unter `NFA-5.1`/`NFA-5.2`
> geführt) ist *keine* Sicherheits-/Datenschutzanforderung, sondern Reporting-Interoperabilität und wird
> daher als **FA-5.6** geführt. NFA-5 beschränkt sich auf Sicherheit und Datenschutz.

---

## 3. Design Principles (DP)

| ID | Design Principle | adressiert | Umsetzende Komponente |
|----|------------------|------------|-----------------------|
| DP-1 | Modulare Agenten-Architektur | FA-1…FA-5, NFA-3 | alle Agenten + `Orchestrator` |
| DP-2 | YAML-Konfigurierbarkeit | FA-1.3, NFA-3 | `config/*.yaml` |
| DP-3 | Erklärbarkeit | NFA-1 | Konfidenz, SHAP, Audit-Trail |
| DP-4 | Compliance-by-Design | FA-3 | `ComplianceAgent` (nach Wesentlichkeit) |
| DP-5 | Doppelte Wesentlichkeit | FA-4 | `MaterialityAgent` |
| DP-6 | SHA-256 Audit-Trail | NFA-2 | `AuditLogger` |

---

## 4. Traceability-Matrix (Anforderung — Komponente — Evidenz)

| Anforderung | Schicht | Datei | Hypothese/Test | Ergebnis |
|-------------|---------|-------|----------------|----------|
| FA-1 | 3 | `agents/data_extraction_agent.py` | H2a | F1 = 1,0 |
| FA-2 | 3 | `agents/validation_agent.py` | H2b / Testfall 4 | Erkennung 1,0 / FP 0,0 |
| FA-3 | 1 | `agents/compliance_agent.py` | FA-3.1 / Testfall 5 | Gap-Recall 1,0 |
| FA-4 | 4 | `agents/materiality_agent.py` | DP-5 | 8/10 Standards material |
| FA-5 | 5 | `agents/report_generation_agent.py` | DP-1 | MD/PDF/JSON |
| NFA-1 | 3 | `evaluation/ml_classifier.py` | H2d | CV-F1 0,9046; Likert-Median 4 |
| NFA-2 | 1 | `utils/audit_logger.py` | Testfall 1 | Manipulation erkannt |
| NFA-3 | — | `config/*.yaml` | H3a / H3b | 10 neue DP; 66,7 % Reuse |
| NFA-4 | — | `agents/orchestrator.py` | H1a | 0,128 s (105 DP) |
| NFA-5 | — | synthetische Daten | — | nur Synth-Daten (DSGVO per Design) |

---

## 5. Erfüllungsübersicht

| Kategorie | erfüllt [x] | teilweise [~] | Roadmap [ ] |
|-----------|-------------|----------------|--------------|
| Muss-Anforderungen | FA-1, FA-1.1, FA-1.3, FA-1.4, FA-2(.1/.2), FA-3(.1), FA-5(.1/.2), NFA-1(.1/.2/.4), NFA-2(.1/.2), NFA-3(.2) | FA-4, NFA-5 | — |
| Soll-Anforderungen | FA-2.3, FA-5.3, FA-5.5, NFA-2.3, NFA-3.1 | FA-1.2, FA-5.4, NFA-1.3, NFA-4 | — |
| Kann-Anforderungen | — | — | FA-5.6 |

> Formulierung für Kapitel 4-Abschluss: „Der MVP erfüllt sämtliche Muss-Anforderungen mit Ausnahme der
> quantitativen Akzeptanzkriterien von FA-4 (Experten-Übereinstimmung nicht erhoben) und NFA-5
> (Sicherheitsmerkmale als Roadmap); die Soll-Anforderungen sind überwiegend erfüllt."

---

## 6. Migrationstabelle (Repo-Alt-ID → kanonische ID)

Grundlage für den nachfolgenden Repo-Patch. Alle abweichenden Repo-IDs werden auf das kanonische Schema
umgestellt; inhaltlich ändert sich nichts.

| Repo-Alt-ID | bisherige Bedeutung (Kontext) | kanonische ID | Begründung |
|-------------|-------------------------------|---------------|------------|
| `NFA-4.1` | SHA-256-Hash-Kette / Audit | **NFA-2.1** | NFA-4 = Skalierbarkeit; Audit gehört zu NFA-2 (Prüfungsfähigkeit) |
| `NFA-4.3` | Audit-Logging | **NFA-2.1** | s. o. |
| `FA-7.1` | „manipulationssicheres Protokoll" | **NFA-2.1** | FA-7 existiert nicht; Audit ist nicht-funktional (NFA-2) |
| `NFA-2.2` *(alt)* | Bericht-PDF-Export | **FA-5.2** | NFA-2 = Audit, nicht Reporting; Export ist FA-5 |
| `FA-4.3` | PDF-Export | **FA-5.2** | FA-4 = Wesentlichkeit; Export ist FA-5 |
| `FA-4.2` | LLM-Narrative im Bericht | **FA-5.4** | Narrative-Generierung ist Berichtserstellung (FA-5) |
| `FA-4.4` | Generierungslogik/Herkunft dokumentiert | **FA-5.5** | Berichts-Provenienz (FA-5), Querbezug NFA-1.1 |
| `NFA-5.1` | EFRAG-Taxonomie-Bezeichnung | **FA-5.6** | ESEF/XBRL ist Reporting-Interoperabilität, nicht Datenschutz |
| `NFA-5.2` | ESEF/ESRS-Taxonomie, maschinenlesbares Reporting | **FA-5.6** | s. o. |

**Bleibt unverändert (bereits kanonisch):**
FA-1, FA-1.1, FA-1.2, FA-1.3, FA-1.4, FA-2, FA-2.1, FA-2.2, FA-2.3, FA-3, FA-3.1, FA-4, FA-5, FA-5.1, FA-5.3,
NFA-1, NFA-1.1, NFA-1.2, NFA-1.3, NFA-1.4, NFA-2.3, NFA-3, NFA-3.1, NFA-3.2, NFA-5, DP-1…DP-6.

---

## 7. Entscheidungsprotokoll der Restpositionen

Beide zuvor offenen Restpositionen sind entschieden und im Katalog eingearbeitet:

1. **ESEF/XBRL (vormals `NFA-5.1`/`NFA-5.2`)** — als **FA-5.6 (maschinenlesbarer ESEF/XBRL-Export, Roadmap, Prio K)**
   geführt. NFA-5 bleibt auf Sicherheit und Datenschutz beschränkt.
2. **`FA-5.3` Human-in-the-Loop** — primär unter **FA-5.3** geführt, mit explizitem Querverweis auf **NFA-1.2**.

Damit ist der Katalog vollständig und bildet die maßgebliche Grundlage für den Repo-Patch (Migrationstabelle,
Abschnitt 6) sowie die anschließende Thesis-Anpassung (Anhang einfügen, Fließtext-IDs angleichen).
