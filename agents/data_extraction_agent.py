"""Data Extraction Agent (UC-02 / FA-1).

Identifiziert und extrahiert ESRS-Datenpunkte gemaess konfigurierten Katalogen (E1-G1). Zwei Backends:

* deterministic: liest strukturierte Werte ueber value_path. Reproduzierbar
  (QA-3.1), API-frei, Konfidenz 1.0 bei Treffer. Baseline fuer die Evaluation.
* claude: serialisiert Unternehmensdaten als Berichtstext, extrahiert Werte via
  LLM (FA-1.2) und gibt Konfidenzwerte 0.0-1.0 zurueck. Gegenstand von H2a.

Fuer jeden Datenpunkt wird die Quellenherkunft dokumentiert (FA-1.4).
"""
from __future__ import annotations

import json
from typing import Any

from agents.base import BaseAgent, ExtractedDatapoint
from utils.config_loader import get_by_path


class DataExtractionAgent(BaseAgent):
    name = "DataExtractionAgent"

    def __init__(self, audit, catalog: dict, backend: str = "deterministic",
                 review_threshold: float = 0.75, llm=None) -> None:
        super().__init__(audit)
        self.catalog = catalog
        self.backend = backend
        self.review_threshold = review_threshold
        self.llm = llm

    def run(self, company_data: dict, source_name: str) -> list[ExtractedDatapoint]:
        self._log("extraction_started", {"backend": self.backend, "source": source_name})
        report_text = self._company_to_text(company_data) if self.backend == "claude" else ""
        results: list[ExtractedDatapoint] = []
        for dp in self.catalog["datapoints"]:
            extracted = self._extract_one(dp, company_data, source_name, report_text)
            results.append(extracted)
            if extracted.present and extracted.confidence < self.review_threshold:
                self._log(
                    "review_required",
                    {"datapoint_id": dp["id"], "reason": "confidence_below_threshold"},
                    confidence=extracted.confidence,
                )
        present = sum(1 for r in results if r.present)
        self._log("extraction_completed",
                  {"datapoints_total": len(results), "datapoints_present": present})
        return results

    def _extract_one(self, dp: dict, data: dict, source_name: str,
                     report_text: str = "") -> ExtractedDatapoint:
        is_narrative = dp["datatype"] == "narrative"

        if self.backend == "deterministic":
            value = get_by_path(data, dp["value_path"])
            present = value is not None and not (is_narrative and str(value).strip() == "")
            confidence = 1.0 if present else 0.0
            source = {"file": source_name, "path": dp["value_path"], "method": "structured_lookup"}
        else:  # claude backend
            value, confidence, present, reasoning = self._llm_extract(dp, report_text)
            if present and is_narrative and value is not None and str(value).strip() == "":
                present = False
            source = {
                "file": source_name,
                "method": "llm_extraction",
                "reasoning": reasoning,
            }

        return ExtractedDatapoint(
            id=dp["id"], dr=dp["dr"], name_de=dp["name_de"], category=dp["category"],
            datatype=dp["datatype"], unit=dp.get("unit", ""), value=value, present=present,
            confidence=confidence, source=source,
        )

    def _llm_extract(self, dp: dict, report_text: str) -> tuple[Any, float, bool]:
        """Extrahiert einen Datenpunkt via LLM aus dem Berichtstext (FA-1.2).

        Gibt (value, confidence, present) zurueck. Faellt bei Fehler auf
        (None, 0.0, False) zurueck damit der Workflow stabil bleibt.
        """
        if self.llm is None:
            return None, 0.0, False

        unit_hint = f" in {dp['unit']}" if dp.get("unit") else ""
        prompt = (
            f"Gegeben ist der folgende Nachhaltigkeitsbericht eines Unternehmens:\n\n"
            f"{report_text}\n\n"
            f"Aufgabe: Extrahiere den Datenpunkt '{dp['name_de']}' "
            f"(ESRS-Anforderung: {dp['dr']}){unit_hint}.\n"
            f"Datentyp: {dp['datatype']}.\n\n"
            f"Antworte ausschliesslich als gueltiges JSON-Objekt:\n"
            f'{{"value": <extrahierter Wert oder null>, "found": true/false, '
            f'"confidence": <0.0-1.0>, "reasoning": "<kurze Begruendung>"}}\n'
            f"Keine weiteren Erklaerungen, kein Markdown."
        )
        try:
            raw = self.llm.complete(
                system=(
                    "Du bist ein ESRS-Extraktions-Assistent. Extrahiere Datenpunkte "
                    "aus Nachhaltigkeitsberichten praezise. Antworte ausschliesslich im "
                    "vorgegebenen JSON-Format, ohne Markdown-Formatierung."
                ),
                prompt=prompt,
            )
            # Markdown-Codeblock entfernen falls vorhanden
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                parts = cleaned.split("```")
                cleaned = parts[1].lstrip("json").strip() if len(parts) > 1 else cleaned

            result = json.loads(cleaned)
            value = result.get("value")
            found = bool(result.get("found", value is not None))
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            reasoning = str(result.get("reasoning", "")).strip()

            # Typkonvertierung fuer numerische Datenpunkte
            if found and value is not None:
                if dp["datatype"] in ("numeric", "percent"):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        confidence = max(0.0, confidence - 0.2)
                elif dp["datatype"] == "integer":
                    try:
                        value = int(float(str(value)))
                    except (ValueError, TypeError):
                        confidence = max(0.0, confidence - 0.2)

            self._log("llm_extraction_ok", {
                "datapoint_id": dp["id"],
                "found": found,
                "confidence": confidence,
                "reasoning": reasoning,
            })
            return value, confidence, found, reasoning

        except Exception as exc:
            self._log("llm_extraction_failed", {"datapoint_id": dp["id"], "error": str(exc)})
            return None, 0.0, False, ""

    def _company_to_text(self, data: dict) -> str:
        """Serialisiert strukturierte Unternehmensdaten als lesbaren Berichtstext.

        Deckt alle 10 ESRS-Standards (E1-E5, S1-S4, G1) ab, damit das LLM-Backend
        Datenpunkte aus saemtlichen Katalogen extrahieren kann.
        Einmalig pro Lauf erzeugt (Effizienz).
        """
        c = data.get("company", {})
        e = data.get("emissions", {})
        en = data.get("energy", {})
        t = data.get("targets", {})
        i = data.get("intensity", {})
        r = data.get("removals", {})
        cp = data.get("carbon_pricing", {})
        fe = data.get("financial_effects", {})
        n = data.get("narratives", {})
        sc3 = e.get("scope_3_categories", {})
        po = data.get("pollution", {})
        w = data.get("water", {})
        b = data.get("biodiversity", {})
        res = data.get("resources", {})
        s1 = data.get("social_own_workforce", {})
        s2 = data.get("social_value_chain", {})
        s3 = data.get("communities", {})
        s4 = data.get("consumers", {})
        g1 = data.get("governance", {})

        lines = [
            f"Unternehmen: {c.get('name', 'n/a')}",
            f"Sektor: {c.get('sector', 'n/a')}, Land: {c.get('country', 'n/a')}",
            f"Berichtsjahr: {c.get('reporting_year', 'n/a')}",
            f"Mitarbeiter (FTE): {c.get('employees_fte', 'n/a')}",
            f"Umsatz: {c.get('revenue_mio_eur', 'n/a')} Mio. EUR",
            f"Bilanzsumme: {c.get('total_assets_mio_eur', 'n/a')} Mio. EUR",
            "",
            "=== ESRS E1: THG-Emissionen ===",
            f"Scope 1: {e.get('scope_1_tco2e', 'n/a')} tCO2e",
            f"  davon ETS-pflichtig: {e.get('scope_1_ets_percent', 'n/a')} %",
            f"Scope 2 (standortbasiert): {e.get('scope_2_location_tco2e', 'n/a')} tCO2e",
            f"Scope 2 (marktbasiert): {e.get('scope_2_market_tco2e', 'n/a')} tCO2e",
            f"Scope 3 gesamt: {e.get('scope_3_total_tco2e', 'n/a')} tCO2e",
            f"  Kategorie 1 (eingekaufte Waren/Dienstl.): {sc3.get('cat_1_purchased_goods', 'n/a')} tCO2e",
            f"  Kategorie 3 (Energie): {sc3.get('cat_3_fuel_energy', 'n/a')} tCO2e",
            f"  Kategorie 6 (Geschaeftsreisen): {sc3.get('cat_6_business_travel', 'n/a')} tCO2e",
            f"  Kategorie 7 (Pendeln Mitarbeitende): {sc3.get('cat_7_employee_commuting', 'n/a')} tCO2e",
            f"  Kategorie 11 (verkaufte Produkte): {sc3.get('cat_11_sold_products', 'n/a')} tCO2e",
            f"  Kategorie 15 (Investitionen): {sc3.get('cat_15_investments', 'n/a')} tCO2e",
            f"THG gesamt (standortbasiert): {e.get('total_ghg_location_tco2e', 'n/a')} tCO2e",
            f"THG gesamt (marktbasiert): {e.get('total_ghg_market_tco2e', 'n/a')} tCO2e",
            f"Biogenes CO2: {e.get('biogenic_co2_tco2e', 'n/a')} tCO2e",
            "",
            "=== ESRS E1: Energieverbrauch ===",
            f"Gesamt: {en.get('total_consumption_mwh', 'n/a')} MWh",
            f"Fossil: {en.get('fossil_mwh', 'n/a')} MWh",
            f"Kernenergie: {en.get('nuclear_mwh', 'n/a')} MWh",
            f"Erneuerbar: {en.get('renewable_mwh', 'n/a')} MWh",
            f"Anteil erneuerbarer Energie: {en.get('renewable_share_percent', 'n/a')} %",
            f"Energieintensitaet: {en.get('energy_intensity_mwh_per_mio_eur', 'n/a')} MWh/Mio. EUR",
            f"Eigenerzeugung erneuerbar: {en.get('own_renewable_generation_mwh', 'n/a')} MWh",
            f"Energieeinsparungen: {en.get('energy_savings_mwh', 'n/a')} MWh",
            "",
            "=== ESRS E1: Klimaziele ===",
            f"Basisjahr: {t.get('base_year', 'n/a')}",
            f"Zieljahr: {t.get('target_year', 'n/a')}",
            f"Reduktionsziel: {t.get('reduction_target_percent', 'n/a')} %",
            f"Netto-Null-Ziel: {t.get('net_zero_year', 'n/a')}",
            f"Scope-1/2-Reduktion vs. Basisjahr: {t.get('scope_1_2_reduction_vs_base_percent', 'n/a')} %",
            "",
            "=== ESRS E1: THG-Intensitaet und finanzierte Emissionen ===",
            f"THG-Intensitaet je Umsatz: {i.get('ghg_intensity_per_revenue', 'n/a')} tCO2e/Mio. EUR",
            f"THG-Intensitaet je FTE: {i.get('ghg_intensity_per_fte', 'n/a')} tCO2e/FTE",
            f"Finanzierte Emissionen je Mio. EUR AuM: {i.get('financed_emissions_per_mio_eur_aum', 'n/a')} tCO2e",
            "",
            "=== ESRS E1: Entnahmen, Kompensation und CO2-Bepreisung ===",
            f"THG-Entnahmen: {r.get('ghg_removals_tco2e', 'n/a')} tCO2e",
            f"CO2-Zertifikate: {r.get('carbon_credits_tco2e', 'n/a')} tCO2e",
            f"Interner CO2-Preis: {cp.get('internal_carbon_price_eur_per_tco2e', 'n/a')} EUR/tCO2e",
            "",
            "=== ESRS E1: Finanzielle Klimarisiken ===",
            f"Vermoegenswerte mit physischem Klimarisiko: {fe.get('assets_at_physical_risk_mio_eur', 'n/a')} Mio. EUR ({fe.get('assets_at_physical_risk_percent', 'n/a')} %)",
            f"Green Asset Ratio: {fe.get('green_asset_ratio_percent', 'n/a')} %",
            f"Transitionsrisikoexposure: {fe.get('transition_risk_exposure_mio_eur', 'n/a')} Mio. EUR",
            f"Green Financing Volumen: {fe.get('green_financing_volume_mio_eur', 'n/a')} Mio. EUR",
            "",
            "=== ESRS E1: Narrative Angaben ===",
            f"Transitionsplan: {n.get('transition_plan', 'n/a')}",
            f"Klimapolitik und -strategie: {n.get('climate_policies', 'n/a')}",
            f"Klimamassnahmen: {n.get('climate_actions', 'n/a')}",
            f"Physische Risiken: {n.get('physical_risks', 'n/a')}",
            f"Transitorische Risiken: {n.get('transition_risks', 'n/a')}",
            f"Klimachancen: {n.get('climate_opportunities', 'n/a')}",
            "",
            "=== ESRS E2: Umweltverschmutzung ===",
            f"Luftemissionen NOx: {po.get('air_emissions_nox_kg', 'n/a')} kg",
            f"Luftemissionen SOx: {po.get('air_emissions_sox_kg', 'n/a')} kg",
            f"Luftemissionen PM2.5: {po.get('air_emissions_pm25_kg', 'n/a')} kg",
            f"Gefaehrliche Abfaelle: {po.get('hazardous_waste_tonnes', 'n/a')} t",
            f"Nicht-gefaehrliche Abfaelle: {po.get('non_hazardous_waste_tonnes', 'n/a')} t",
            f"Abwassereinleitung: {po.get('wastewater_discharged_m3', 'n/a')} m3",
            f"Umweltvorfaelle: {po.get('pollution_incidents_count', 'n/a')}",
            f"Finanziertes Verschmutzungsexposure: {po.get('financed_pollution_exposure_percent', 'n/a')} %",
            "",
            "=== ESRS E3: Wasser und Meeresressourcen ===",
            f"Gesamtverbrauch: {w.get('total_consumption_m3', 'n/a')} m3",
            f"Gesamtentnahme: {w.get('total_withdrawal_m3', 'n/a')} m3",
            f"Wiederverwendetes Wasser: {w.get('recycled_water_m3', 'n/a')} m3",
            f"Wasserintensitaet: {w.get('water_intensity_m3_per_fte', 'n/a')} m3/FTE",
            f"Entnahme in Wasserstressgebieten: {w.get('water_stress_area_withdrawal_percent', 'n/a')} %",
            f"Finanziertes wasserintensives Exposure: {w.get('financed_water_intensive_exposure_percent', 'n/a')} %",
            "",
            "=== ESRS E4: Biodiversitaet ===",
            f"Landnutzung: {b.get('land_use_m2', 'n/a')} m2",
            f"Versiegelte Flaeche: {b.get('sealed_surface_m2', 'n/a')} m2",
            f"Betrieb in Schutzgebieten: {b.get('operations_in_protected_areas', 'n/a')}",
            f"Finanziertes Schutzgebiets-Exposure: {b.get('financed_sensitive_area_exposure_percent', 'n/a')} %",
            f"Biodiversitaets-Nettoimpact-Score: {b.get('biodiversity_net_impact_score', 'n/a')}",
            "",
            "=== ESRS E5: Ressourcennutzung und Kreislaufwirtschaft ===",
            f"Abfall gesamt: {res.get('total_waste_tonnes', 'n/a')} t",
            f"Recyclingquote: {res.get('recycling_rate_percent', 'n/a')} %",
            f"Papierverbrauch: {res.get('paper_consumption_kg_per_fte', 'n/a')} kg/FTE",
            f"Anteil aufbereiteter IT-Geraete: {res.get('it_equipment_refurbished_percent', 'n/a')} %",
            f"Zirkulaere Beschaffungsquote: {res.get('circular_procurement_share_percent', 'n/a')} %",
            f"Finanziertes ressourcenintensives Exposure: {res.get('financed_resource_intensive_exposure_percent', 'n/a')} %",
            "",
            "=== ESRS S1: Eigene Belegschaft ===",
            f"Gender Pay Gap: {s1.get('gender_pay_gap_percent', 'n/a')} %",
            f"Verletzungsrate: {s1.get('injury_rate_per_1000_fte', 'n/a')} je 1.000 FTE",
            f"Schulungsstunden: {s1.get('training_hours_per_fte', 'n/a')} h/FTE",
            f"Fluktuationsrate: {s1.get('turnover_rate_percent', 'n/a')} %",
            f"Frauenanteil Fuehrung: {s1.get('female_leadership_percent', 'n/a')} %",
            f"Mitarbeiterengagement: {s1.get('employee_engagement_score', 'n/a')}",
            f"Tarifbindungsquote: {s1.get('collective_bargaining_coverage_percent', 'n/a')} %",
            f"Beschaeftigte unter Existenzlohn: {s1.get('employees_below_living_wage_percent', 'n/a')} %",
            f"Inklusion (Behinderung): {s1.get('disability_inclusion_percent', 'n/a')} %",
            "",
            "=== ESRS S2: Wertschoepfungskette ===",
            f"Aktive Lieferanten: {s2.get('active_suppliers_count', 'n/a')}",
            f"Lieferantenaudits: {s2.get('supplier_audits_count', 'n/a')}",
            f"Hochrisiko-Lieferanten: {s2.get('high_risk_suppliers_percent', 'n/a')} %",
            f"Lieferanten mit Verhaltenskodex: {s2.get('suppliers_with_code_of_conduct_percent', 'n/a')} %",
            f"Menschenrechtsverletzungen in der Kette: {s2.get('human_rights_violations_in_chain_count', 'n/a')}",
            f"Finanziertes Lieferketten-Risikoexposure: {s2.get('financed_supply_chain_risk_exposure_percent', 'n/a')} %",
            "",
            "=== ESRS S3: Betroffene Gemeinschaften ===",
            f"Gemeinschaftsinvestitionen: {s3.get('community_investment_mio_eur', 'n/a')} Mio. EUR",
            f"Eingegangene Beschwerden: {s3.get('complaints_received_count', 'n/a')}",
            f"Beschwerden geloest: {s3.get('complaints_resolved_percent', 'n/a')} %",
            f"Lokale Beschaffungsquote: {s3.get('local_procurement_percent', 'n/a')} %",
            f"Sozialfinanzierungsvolumen: {s3.get('social_finance_volume_mio_eur', 'n/a')} Mio. EUR",
            "",
            "=== ESRS S4: Verbraucher und Endnutzer ===",
            f"Kundenbeschwerden: {s4.get('customer_complaints_per_1000', 'n/a')} je 1.000 Kunden",
            f"Datenpannen: {s4.get('data_breaches_count', 'n/a')}",
            f"Fehlverkaufsfaelle: {s4.get('product_mis_selling_cases_count', 'n/a')}",
            f"Kundenzufriedenheit: {s4.get('customer_satisfaction_score', 'n/a')}",
            f"Anteil gefaehrdeter Kunden: {s4.get('vulnerable_customer_share_percent', 'n/a')} %",
            f"Finanzinklusions-Produkte: {s4.get('financial_inclusion_products_count', 'n/a')}",
            "",
            "=== ESRS G1: Unternehmensfuehrung ===",
            f"Compliance-Vorfaelle: {g1.get('compliance_violations_count', 'n/a')}",
            f"Antikorruptionstraining: {g1.get('anti_corruption_training_percent', 'n/a')} %",
            f"Whistleblowing-Meldungen gesamt: {g1.get('whistleblowing_cases_count', 'n/a')}",
            f"Whistleblowing-Meldungen bestaetigt: {g1.get('whistleblowing_cases_substantiated_count', 'n/a')}",
            f"Unabhaengige Aufsichtsratsmitglieder: {g1.get('board_independence_percent', 'n/a')} %",
            f"Frauenanteil Aufsichtsrat: {g1.get('women_on_board_percent', 'n/a')} %",
            f"Bussgelder gesamt: {g1.get('fines_total_mio_eur', 'n/a')} Mio. EUR",
            f"Steuerberichterstattung veroeffentlicht: {g1.get('tax_transparency_published', 'n/a')}",
            f"Lobbying-Ausgaben: {g1.get('lobbying_expenses_mio_eur', 'n/a')} Mio. EUR",
        ]
        return "\n".join(lines)
