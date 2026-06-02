"""Report Generation Agent (UC-05 / FA-4 / Schicht 5).

Erstellt vollstaendige ESRS-Disclosure-Berichte (Markdown + Lagebericht-Interpretation, alle Standards)
aus validierten Daten und AssessmentErgebnis. Jede Sektion erhaelt narrative Interpretation.
Narrative Abschnitte koennen via LLM erzeugt werden (NFA-1.3 / FA-4.2).
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.base import BaseAgent, ComplianceResult, ExtractedDatapoint, ValidationIssue
from utils.config_loader import get_by_path

_AMPEL_EMOJI = {"GRUEN": "🟢", "GELB": "🟡", "ROT": "🔴", "NEUTRAL": "⚪"}
_AMPEL_TEXT = {"GRUEN": "GRUEN", "GELB": "GELB", "ROT": "ROT", "NEUTRAL": "n/a"}


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def _ampel_symbol(ampel: str) -> str:
    return f"{_AMPEL_EMOJI.get(ampel, '⚪')} {_AMPEL_TEXT.get(ampel, 'n/a')}"


class ReportGenerationAgent(BaseAgent):
    name = "ReportGenerationAgent"

    def __init__(self, audit, template: str, language: str = "de",
                 backend: str = "deterministic", llm=None) -> None:
        super().__init__(audit)
        self.template = template
        self.language = language
        self.backend = backend
        self.llm = llm

    def run(self, company_data: dict, extracted: list[ExtractedDatapoint],
            validation: list[ValidationIssue], compliance: ComplianceResult,
            assessment=None, materiality=None) -> str:
        self._log("report_generation_started", {"backend": self.backend})
        by_id = {e.id: e for e in extracted}
        company = company_data.get("company", {})
        self._materiality = materiality
        self._assessment = assessment

        use_llm = self.backend == "claude" and self.llm is not None and self.llm.available
        exec_summary = self._executive_summary(by_id, compliance, assessment, materiality, use_llm)

        # -- Assessment-Texte --------------------------------------------------
        gesamt_ampel = "n/a"
        gesamt_text = ""
        staerken_liste = "_Keine Staerken identifiziert._"
        schwaechen_liste = "_Kein Handlungsbedarf identifiziert._"
        kpi_tabelle = "_KPI-Bewertung nicht verfuegbar (Assessment nicht ausgefuehrt)._"
        empfehlungen_liste = "_Keine Empfehlungen._"
        abschnitt_klimastrategie = "_Klimastrategie-Analyse nicht verfuegbar._"
        abschnitt_thg = "_THG-Analyse nicht verfuegbar._"
        abschnitt_energie = "_Energie-Analyse nicht verfuegbar._"
        abschnitt_ziele = "_Klimaziel-Analyse nicht verfuegbar._"
        abschnitt_risiken = "_Risikoanalyse nicht verfuegbar._"
        abschnitt_nachhalt = "_Nachhaltigkeitsfinanzierungs-Analyse nicht verfuegbar._"

        if assessment is not None:
            gesamt_ampel = _ampel_symbol(assessment.gesamtampel)
            sek = assessment.lagebericht_abschnitte
            gesamt_text = sek.get("gesamtbewertung", "")
            abschnitt_klimastrategie = sek.get("klimastrategie", "")
            abschnitt_thg = sek.get("thg_emissionen", "")
            abschnitt_energie = sek.get("energie", "")
            abschnitt_ziele = sek.get("klimaziele", "")
            abschnitt_risiken = sek.get("klimarisiken", "")
            abschnitt_nachhalt = sek.get("nachhaltige_finanzierung", "")

            if assessment.staerken:
                staerken_liste = "\n".join(f"- {s}" for s in assessment.staerken)
            if assessment.schwaechen:
                schwaechen_liste = "\n".join(f"- {s}" for s in assessment.schwaechen)
            if assessment.handlungsempfehlungen:
                empfehlungen_liste = "\n".join(
                    f"{i+1}. {e}" for i, e in enumerate(assessment.handlungsempfehlungen)
                )
            kpi_tabelle = self._kpi_bewertung_tabelle(assessment)

        report = self.template.format(
            company_name=company.get("name", "n/a"),
            company_sector=company.get("sector", "n/a"),
            company_country=company.get("country", "n/a"),
            reporting_year=company.get("reporting_year", "n/a"),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            executive_summary=exec_summary,
            gesamtampel=gesamt_ampel,
            gesamtbewertung_text=gesamt_text,
            staerken_liste=staerken_liste,
            schwaechen_liste=schwaechen_liste,
            abschnitt_klimastrategie=abschnitt_klimastrategie,
            narrative_transition_plan=self._narr(by_id, "E1-DP-029"),
            narrative_climate_policies=self._narr(by_id, "E1-DP-030"),
            narrative_climate_actions=self._narr(by_id, "E1-DP-031"),
            narrative_physical_risks=self._narr(by_id, "E1-DP-032"),
            narrative_transition_risks=self._narr(by_id, "E1-DP-033"),
            narrative_climate_opportunities=self._narr(by_id, "E1-DP-034"),
            abschnitt_energie=abschnitt_energie,
            abschnitt_thg_emissionen=abschnitt_thg,
            abschnitt_klimaziele=abschnitt_ziele,
            abschnitt_klimarisiken=abschnitt_risiken,
            abschnitt_nachhaltige_finanzierung=abschnitt_nachhalt,
            table_energy=self._table(extracted, ["energy"]),
            table_targets=self._table(extracted, ["targets"]),
            table_emissions=self._table(extracted, ["emissions", "intensity"]),
            table_other=self._table(extracted, ["removals", "carbon_pricing", "financial_effects"]),
            weitere_standards_abschnitte=self._weitere_standards_abschnitte(extracted, assessment, materiality),
            kpi_bewertung_tabelle=kpi_tabelle,
            handlungsempfehlungen_liste=empfehlungen_liste,
            provenance_table=self._provenance(extracted),
            compliance_status=compliance.status,
            completeness=(
                f"{compliance.completeness_rate * 100:.1f}% "
                f"({compliance.present_mandatory}/{compliance.total_mandatory} Pflichtdatenpunkte)"
            ),
        )
        self._log("report_generation_completed", {"length_chars": len(report)})
        return report

    def _narr(self, by_id: dict, dp_id: str) -> str:
        e = by_id.get(dp_id)
        if e is None or not e.present:
            return "_Nicht verfuegbar (Pflichtangabe fehlt)._"
        return str(e.value)

    def _table(self, extracted: list[ExtractedDatapoint], categories: list[str]) -> str:
        rows = [e for e in extracted if e.category in categories and e.datatype != "narrative"]
        if not rows:
            return "_Keine Datenpunkte._"
        lines = ["| Datenpunkt | DR | Wert | Einheit | Konfidenz | Quelle |",
                 "|---|---|---|---|---|---|"]
        for e in rows:
            value = _fmt(e.value) if e.present else "_fehlt_"
            conf = f"{e.confidence:.2f}" if e.present else "-"
            src = e.source.get("path", "-")
            lines.append(
                f"| {e.name_de} | {e.dr} | {value} | {e.unit} | {conf} | `{src}` |"
            )
        return "\n".join(lines)

    def _kpi_bewertung_tabelle(self, assessment) -> str:
        if not assessment or not assessment.kpi_bewertungen:
            return "_Keine KPI-Bewertungen verfuegbar._"
        lines = [
            "| Standard | KPI | Wert | Einheit | Sektormedian | Ampel | Interpretation |",
            "|---|---|---|---|---|---|---|",
        ]
        for b in assessment.kpi_bewertungen:
            ampel = _ampel_symbol(b.ampel)
            median_str = _fmt(b.sektor_p50) if b.sektor_p50 is not None else "n/a"
            wert_str = _fmt(b.wert) if b.wert is not None else "**FEHLT**"
            std = b.dp_id.split("-")[0]
            interp = b.interpretation if b.ampel != "NEUTRAL" else f"⚠️ {b.interpretation}"
            lines.append(
                f"| {std} | {b.name_de} | {wert_str} | {b.einheit} | {median_str} | {ampel} | {interp} |"
            )
        return "\n".join(lines)

    def _weitere_standards_abschnitte(
        self, extracted: list, assessment, materiality
    ) -> str:
        """Generiert Markdown-Abschnitte fuer alle wesentlichen Standards ausser E1."""
        _STANDARD_META = {
            "E2": ("ESRS E2 — Umweltverschmutzung", "E2-"),
            "E3": ("ESRS E3 — Wasser- und Meeresressourcen", "E3-"),
            "E4": ("ESRS E4 — Biodiversitaet und Oekosysteme", "E4-"),
            "E5": ("ESRS E5 — Ressourcennutzung und Kreislaufwirtschaft", "E5-"),
            "S1": ("ESRS S1 — Eigene Belegschaft", "S1-"),
            "S2": ("ESRS S2 — Arbeitskraefte in der Wertschoepfungskette", "S2-"),
            "S3": ("ESRS S3 — Betroffene Gemeinschaften", "S3-"),
            "S4": ("ESRS S4 — Verbraucher und Endnutzer", "S4-"),
            "G1": ("ESRS G1 — Unternehmenspolitik / Governance", "G1-"),
        }

        # Wesentliche Standards ermitteln
        wesentlich_ids = set()
        if materiality:
            for t in materiality.themen:
                if t.wesentlich and t.id != "E1":
                    wesentlich_ids.add(t.id)

        # KPI-Bewertungen nach Standard gruppieren
        bew_by_std: dict = {}
        if assessment:
            for b in assessment.kpi_bewertungen:
                std = b.dp_id.split("-")[0]
                bew_by_std.setdefault(std, []).append(b)

        sections = []
        for std_id, (label, prefix) in _STANDARD_META.items():
            # Extrahierte Datenpunkte fuer diesen Standard
            dps = [e for e in extracted if e.id.startswith(prefix) and e.present
                   and e.datatype != "narrative"]
            bewertungen = bew_by_std.get(std_id, [])

            wesentlich = std_id in wesentlich_ids
            status_marker = "" if wesentlich else " *(nicht wesentlich — Transparenzangabe)*"

            section = [f"### {label}{status_marker}", ""]

            if not wesentlich:
                section.append(
                    "_Dieser Standard wurde in der Wesentlichkeitsanalyse als nicht wesentlich "
                    "eingestuft. Nachfolgende Datenpunkte werden zur Transparenz ausgewiesen, "
                    "erfordern jedoch gemaess ESRS 1 Kap. 3.4 keine verpflichtende Offenlegung._"
                )
                section.append("")

            # Gesamtinterpretation aus KPI-Bewertungen
            if bewertungen:
                section.append(self._gesamtinterpretation_standard(std_id, label, bewertungen))
                section.append("")

            # KPI-Tabelle
            if dps:
                section.append("| Datenpunkt | DR | Wert | Einheit |")
                section.append("|---|---|---|---|")
                for e in dps:
                    section.append(
                        f"| {e.name_de} | {e.dr} | {_fmt(e.value)} | {e.unit or '—'} |"
                    )
                section.append("")

            # KPI-Bewertungen
            if bewertungen:
                section.append("**Sektorvergleich:**")
                section.append("")
                section.append("| KPI | Wert | Sektormedian | Ampel |")
                section.append("|---|---|---|---|")
                for b in bewertungen:
                    median_str = _fmt(b.sektor_p50) if b.sektor_p50 is not None else "n/a"
                    section.append(
                        f"| {b.name_de} | {_fmt(b.wert)} {b.einheit} | "
                        f"{median_str} {b.einheit} | {_ampel_symbol(b.ampel)} |"
                    )
                section.append("")

            sections.append("\n".join(section))

        return "\n---\n\n".join(sections) if sections else "_Keine weiteren Standards berichtet._"

    def _gesamtinterpretation_standard(
        self, std_id: str, label: str, bewertungen: list
    ) -> str:
        """Erzeugt eine ausfuehrliche Gesamtinterpretation fuer einen Standard."""
        gruen = [b for b in bewertungen if b.ampel == "GRUEN"]
        gelb  = [b for b in bewertungen if b.ampel == "GELB"]
        rot   = [b for b in bewertungen if b.ampel == "ROT"]
        neut  = [b for b in bewertungen if b.ampel == "NEUTRAL"]

        # Alle Daten fehlen
        if not gruen and not gelb and not rot:
            missing = ", ".join(b.name_de for b in neut[:5])
            return (
                f"**Gesamtstatus {label}: KEINE BELASTBARE AUSSAGE MOEGLICH** — "
                f"Alle {len(neut)} Datenpunkte dieses Standards fehlen in den Eingabedaten. "
                f"Fehlende Kennzahlen: {missing}. "
                f"Die Sektormediane sind als Orientierung in der Tabelle hinterlegt. "
                f"Bitte die entsprechenden Datenfelder erganzen und den Workflow erneut ausfuehren."
            )

        bewertet = len(gruen) + len(gelb) + len(rot)
        if rot:
            gesamt_status = "kritischer Handlungsbedarf"
        elif gelb:
            gesamt_status = "Verbesserungspotenzial vorhanden"
        else:
            gesamt_status = "gut aufgestellt im Sektorvergleich"

        lines = [
            f"**Gesamtstatus {label}:** Das Unternehmen ist in diesem Bereich "
            f"**{gesamt_status}** ({len(gruen)} GRUEN / {len(gelb)} GELB / {len(rot)} ROT"
            f", bewertet: {bewertet}/{len(bewertungen)} KPIs). "
        ]
        if neut:
            lines.append(
                f"Hinweis: {len(neut)} Kennzahl(en) ohne Eingabedaten — "
                "keine belastbare Aussage moeglich: " +
                ", ".join(b.name_de for b in neut) + ". "
            )
        if gruen:
            staerken = ", ".join(f"{b.name_de} ({_fmt(b.wert)} {b.einheit})" for b in gruen[:3])
            lines.append(f"Staerken: {staerken}. ")
        if rot:
            schwaechen = "; ".join(
                f"{b.name_de} ({_fmt(b.wert)} {b.einheit}, "
                f"Sektormedian {_fmt(b.sektor_p50)} {b.einheit}): {b.interpretation}"
                for b in rot
            )
            lines.append(f"Kritische Bereiche: {schwaechen}. ")
        if gelb:
            mittel = ", ".join(f"{b.name_de} ({_fmt(b.wert)} {b.einheit})" for b in gelb[:2])
            lines.append(f"Mittlerer Handlungsbedarf: {mittel}. ")
        if rot:
            empfehlungen = "; ".join(b.empfehlung for b in rot[:2] if b.empfehlung)
            if empfehlungen:
                lines.append(f"Prioritaere Massnahmen: {empfehlungen}.")

        return "".join(lines)

    def _provenance(self, extracted: list[ExtractedDatapoint]) -> str:
        lines = ["| Datenpunkt-ID | Methode | Konfidenz | Pfad | Status |",
                 "|---|---|---|---|---|"]
        for e in extracted:
            status = "vorhanden" if e.present else "FEHLT"
            lines.append(
                f"| {e.id} | {e.source.get('method', '-')} | "
                f"{e.confidence:.2f} | `{e.source.get('path', '-')}` | {status} |"
            )
        return "\n".join(lines)

    def _executive_summary(self, by_id: dict, compliance: ComplianceResult,
                           assessment=None, materiality=None,
                           use_llm: bool = False) -> str:
        """Ausfuehrliches Executive Summary ueber alle wesentlichen Standards."""
        company = {}
        lines = []

        # --- Einleitung ---
        co_name = by_id.get("E1-DP-007")  # Proxy fuer Unternehmen vorhanden
        lines.append(
            "Dieser Bericht dokumentiert die Nachhaltigkeitsoffenlegungen gemaess CSRD "
            "und den European Sustainability Reporting Standards (ESRS, Amended Exposure "
            "Drafts Juli 2025). Grundlage ist die doppelte Wesentlichkeitsanalyse nach "
            "ESRS 1 (IRO-1), die bestimmt, zu welchen Themen Angaben zu machen sind. "
            "Die Erstellung erfolgte durch ein KI-Agenten-Framework (Weiss, Frankfurt "
            "School, 2025/2026); alle Inhalte sind vor produktivem Einsatz fachlich zu pruefen."
        )
        lines.append("")

        # --- Wesentlichkeitsanalyse ---
        if materiality:
            wesentlich = [t for t in materiality.themen if t.wesentlich]
            nicht_wes = [t for t in materiality.themen if not t.wesentlich]
            lines.append(
                f"**Wesentlichkeitsanalyse:** {len(wesentlich)} von "
                f"{len(materiality.themen)} ESRS-Standards sind wesentlich und werden "
                f"vollstaendig offengelegt: "
                + ", ".join(t.standard for t in wesentlich) + ". "
                + (f"Nicht wesentlich: {', '.join(t.standard for t in nicht_wes)}."
                   if nicht_wes else "")
            )
            lines.append("")

        # --- Compliance-Status ---
        lines.append(
            f"**Compliance-Status:** {compliance.status} — "
            f"{compliance.completeness_rate * 100:.0f}% der Pflichtdatenpunkte "
            f"wesentlicher Standards vorhanden "
            f"({compliance.present_mandatory}/{compliance.total_mandatory})."
        )
        lines.append("")

        # --- E1 Klimaperformance ---
        if assessment:
            total = by_id.get("E1-DP-007")
            scope3 = by_id.get("E1-DP-005")
            cat15 = None
            for dp in by_id.values():
                if dp.id == "E1-DP-009":
                    cat15 = dp
                    break
            renew = by_id.get("E1-DP-017")
            target = by_id.get("E1-DP-021")
            net_zero = by_id.get("E1-DP-022")
            carbon_price = by_id.get("E1-DP-026")

            lines.append(
                f"**ESRS E1 — Klimawandel ({_ampel_symbol(assessment.gesamtampel)}):** "
                f"Die Gesamtbewertung der Klimaperformance im Sektorvergleich ergibt "
                f"**{assessment.gesamtampel}**. "
                f"Gesamte THG-Emissionen (marktbasiert): "
                f"{_fmt(total.value) if total and total.present else 'n/a'} tCO2e, "
                f"davon Scope-3-Kategorie-15 (finanzierte Emissionen) als dominanter Treiber. "
                f"Anteil erneuerbarer Energie: "
                f"{_fmt(renew.value) if renew and renew.present else 'n/a'}%. "
                f"THG-Reduktionsziel: {_fmt(target.value) if target and target.present else 'n/a'}% "
                f"bis 2030; Netto-Null bis "
                f"{int(net_zero.value) if net_zero and net_zero.present else 'n/a'}. "
                f"Interner CO2-Preis: "
                f"{_fmt(carbon_price.value) if carbon_price and carbon_price.present else 'n/a'} EUR/tCO2e."
            )
            lines.append("")

            # Staerken und Schwaechen
            if assessment.staerken:
                lines.append("Klimastaerken: " + "; ".join(assessment.staerken[:3]) + ".")
            if assessment.schwaechen:
                lines.append("Handlungsbedarf Klima: " + "; ".join(assessment.schwaechen[:3]) + ".")
            lines.append("")

        # --- Uebersicht weitere wesentliche Standards ---
        if assessment and materiality:
            andere = [t for t in materiality.themen if t.wesentlich and t.id != "E1"]
            if andere:
                bew_by_std: dict = {}
                for b in assessment.kpi_bewertungen:
                    std = b.dp_id.split("-")[0]
                    bew_by_std.setdefault(std, []).append(b)

                lines.append("**Weitere wesentliche Standards — Kurzuebersicht:**")
                lines.append("")
                lines.append("| Standard | KPIs bewertet | Status | Wichtigste Erkenntnis |")
                lines.append("|---|---|---|---|")
                for t in andere:
                    bewertungen = bew_by_std.get(t.id, [])
                    if not bewertungen:
                        lines.append(f"| {t.standard} | — | — | Keine Benchmark-Bewertung verfuegbar |")
                        continue
                    rot = sum(1 for b in bewertungen if b.ampel == "ROT")
                    gelb = sum(1 for b in bewertungen if b.ampel == "GELB")
                    gruen = sum(1 for b in bewertungen if b.ampel == "GRUEN")
                    if rot > 0:
                        status = f"🔴 {rot}x ROT"
                    elif gelb > 0:
                        status = f"🟡 {gelb}x GELB"
                    else:
                        status = f"🟢 {gruen}x GRUEN"
                    # Wichtigste Erkenntnis: schlechtester KPI
                    worst = next((b for b in bewertungen if b.ampel == "ROT"),
                                 next((b for b in bewertungen if b.ampel == "GELB"),
                                      bewertungen[0] if bewertungen else None))
                    erkenntnis = f"{worst.name_de}: {_fmt(worst.wert)} {worst.einheit}" if worst else "—"
                    lines.append(f"| {t.standard} | {len(bewertungen)} | {status} | {erkenntnis} |")
                lines.append("")

        # --- Top-Empfehlungen ---
        if assessment and assessment.handlungsempfehlungen:
            lines.append("**Top-Handlungsempfehlungen:**")
            lines.append("")
            for emp in assessment.handlungsempfehlungen[:5]:
                lines.append(f"- {emp}")
            lines.append("")

        result = "\n".join(lines)

        if use_llm:
            try:
                text = self.llm.complete(
                    system=(
                        "Du bist ein ESG-Reporting-Experte fuer Finanzinstitute. "
                        "Schreibe eine ausfuehrliche, sachliche Executive Summary "
                        "auf Basis der gelieferten Fakten. Verwende CSRD/ESRS-Fachsprache."
                    ),
                    prompt=(
                        f"Schreibe eine ausfuehrliche Executive Summary (ca. 300 Woerter) "
                        f"fuer den CSRD/ESRS-Nachhaltigkeitsbericht auf Basis dieser Fakten:\n{result}\n"
                        f"Betone: Wesentlichkeitsergebnisse, E1-Klimaperformance, "
                        f"Status weiterer Standards, Top-Massnahmen."
                    ),
                )
                self._log("llm_narrative_generated", {"section": "executive_summary"})
                return f"{text}\n\n*(KI-generiert mit {self.llm.model}; vor Verwendung fachlich pruefen.)*"
            except Exception as exc:
                self._log("llm_narrative_failed", {"error": str(exc)})

        return result
