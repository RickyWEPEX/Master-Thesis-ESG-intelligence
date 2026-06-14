"""Data Integration & Management Layer (Schicht 2 der 5-Schichten-Architektur).

Unterstuetzt heterogene Datenquellen gemaess Thesis-Anforderung FA-1.1/FA-1.2:
  - JSON  (strukturiert, Standard)
  - CSV   (tabellarisch, z.B. Excel-Export)
  - XBRL  (maschinenlesbares Reporting-Format, ESEF/ESRS-Taxonomie, FA-5.6)
  - Text  (unstrukturiert, via LLM-Extraktion)

Umsetzt NFA-3.2 (konfigurierbar ohne Code-Aenderung) und NFA-2.1 (Audit-Logging).
"""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class IngestionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# XBRL-Konzept-Mapping (ESRS-Taxonomie -> internes value_path-Schema)
# Konfigurierbar gemaess NFA-3.2: neue Konzepte ohne Code-Aenderung ergaenzbar.
# Schluessel = lokaler XBRL-Konzeptname (ohne Namespace-Praefix).
# ---------------------------------------------------------------------------
XBRL_CONCEPT_MAP: dict[str, str] = {
    # E1-6 THG-Emissionen
    "GrossScope1GreenhouseGasEmissions": "emissions.scope_1_tco2e",
    "PercentageScope1EmissionsRegulatedEmissionTradingSchemes": "emissions.scope_1_ets_percent",
    "GrossLocationBasedScope2GreenhouseGasEmissions": "emissions.scope_2_location_tco2e",
    "GrossMarketBasedScope2GreenhouseGasEmissions": "emissions.scope_2_market_tco2e",
    "GrossScope3GreenhouseGasEmissions": "emissions.scope_3_total_tco2e",
    "TotalLocationBasedGreenhouseGasEmissions": "emissions.total_ghg_location_tco2e",
    "TotalMarketBasedGreenhouseGasEmissions": "emissions.total_ghg_market_tco2e",
    "BiogenicCarbonDioxideEmissions": "emissions.biogenic_co2_tco2e",
    # E1-4 Energie
    "TotalEnergyConsumption": "energy.total_consumption_mwh",
    "EnergyConsumptionFromFossilSources": "energy.fossil_mwh",
    "EnergyConsumptionFromNuclearSources": "energy.nuclear_mwh",
    "EnergyConsumptionFromRenewableSources": "energy.renewable_mwh",
    "ShareOfRenewableEnergy": "energy.renewable_share_percent",
    "EnergyIntensityPerNetRevenue": "energy.energy_intensity_mwh_per_mio_eur",
    # E1-5 Ziele
    "GreenhouseGasEmissionReductionTargetBaseYear": "targets.base_year",
    "GreenhouseGasEmissionReductionTargetYear": "targets.target_year",
    "GreenhouseGasEmissionReductionTargetPercentage": "targets.reduction_target_percent",
    "NetZeroTargetYear": "targets.net_zero_year",
    # E1-6 Intensitaet
    "GreenhouseGasIntensityPerNetRevenue": "intensity.ghg_intensity_per_revenue",
    # E1-9 Entnahmen
    "GreenhouseGasRemovals": "removals.ghg_removals_tco2e",
    "CarbonCreditsPurchasedCancelled": "removals.carbon_credits_tco2e",
    # E1-10 Carbon Pricing
    "InternalCarbonPriceApplied": "carbon_pricing.internal_carbon_price_eur_per_tco2e",
    # E1-11 Finanzielle Effekte
    "AssetsAtMaterialPhysicalRiskMonetary": "financial_effects.assets_at_physical_risk_mio_eur",
    "AssetsAtMaterialPhysicalRiskPercentage": "financial_effects.assets_at_physical_risk_percent",
    "GreenAssetRatio": "financial_effects.green_asset_ratio_percent",
}


def _ingest_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _ingest_csv(path: Path) -> dict:
    """Wandelt eine flache CSV-Tabelle in das interne JSON-Schema um.

    Erwartet Spalten: section, key, value (optional: unit).
    Beispiel:
      section,key,value
      emissions,scope_1_tco2e,1250.5
      energy,renewable_share_percent,45.0
    """
    data: dict[str, Any] = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        raise IngestionError(f"CSV-Datei leer oder ohne Datenzeilen: {path}")

    required = {"section", "key", "value"}
    if not required.issubset({c.strip().lower() for c in rows[0].keys()}):
        raise IngestionError(
            f"CSV muss Spalten 'section', 'key', 'value' enthalten. Gefunden: {list(rows[0].keys())}"
        )

    for row in rows:
        section = row.get("section", "").strip()
        key = row.get("key", "").strip()
        raw_value = row.get("value", "").strip()
        if not section or not key:
            continue
        try:
            value: Any = float(raw_value) if "." in raw_value else int(raw_value)
        except (ValueError, TypeError):
            value = raw_value

        if section not in data:
            data[section] = {}

        # Punktnotation fuer verschachtelte Schluessel (z.B. scope_3_categories.cat_15)
        parts = key.split(".")
        target = data[section]
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    return data


def _ingest_text(text_content: str, llm=None, company_hint: str = "") -> dict:
    """Extrahiert strukturierte ESG-Daten aus Freitext via LLM.

    Faellt ohne LLM auf leere Stub-Struktur zurueck (fuer Tests).
    """
    if llm is None or not llm.available:
        return {
            "company": {"name": company_hint or "Unbekannt", "reporting_year": 2025},
            "_ingestion_note": "Kein LLM verfuegbar; manuelle Befuellung erforderlich.",
        }

    prompt = (
        f"Extrahiere aus folgendem Text die ESG-Kennzahlen eines Unternehmens "
        f"und gib sie als JSON-Objekt zurueck. Nutze folgende Struktur:\n"
        f'{{"company": {{"name": ..., "reporting_year": ...}}, '
        f'"emissions": {{"scope_1_tco2e": ..., ...}}, '
        f'"energy": {{"renewable_share_percent": ..., ...}}, '
        f'"targets": {{"reduction_target_percent": ..., "net_zero_year": ...}}}}\n\n'
        f"Text:\n{text_content[:4000]}\n\n"
        f"Antworte nur mit dem JSON-Objekt, kein Markdown."
    )
    raw = llm.complete(
        system="Du bist ein ESG-Daten-Extraktions-Assistent. Antworte nur mit validem JSON.",
        prompt=prompt,
    )
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise IngestionError(f"LLM-Antwort kein gueltiges JSON: {exc}") from exc


def _set_path(data: dict, dotted_path: str, value: Any) -> None:
    """Setzt einen verschachtelten Wert via Punktnotation (legt Ebenen an)."""
    parts = dotted_path.split(".")
    target = data
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _coerce_number(text: str) -> Any:
    """Wandelt XBRL-Faktentext in Zahl um (entfernt Tausendertrennzeichen)."""
    raw = (text or "").strip().replace(",", "")
    if raw == "":
        return None
    try:
        num = float(raw)
        return int(num) if num.is_integer() else num
    except (ValueError, TypeError):
        return text.strip()


def _ingest_xbrl(path: Path, concept_map: dict[str, str] | None = None) -> dict:
    """Parst ein XBRL-Instanzdokument (ESEF/ESRS-Taxonomie) in das interne Schema.

    Liest XBRL-Fakten (Tags mit contextRef) und mappt deren lokale Konzeptnamen
    via concept_map auf interne value_paths. Namespaces werden ignoriert
    (lokaler Tag-Name nach '}'). Unterstuetzt sowohl inline-XBRL (iXBRL/XHTML)
    als auch klassische XBRL-Instanzen (.xbrl/.xml).

    Gemaess FA-5.6 (maschinenlesbares Reporting) und FA-1.1.
    """
    concept_map = concept_map or XBRL_CONCEPT_MAP
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise IngestionError(f"XBRL/XML nicht parsebar: {exc}") from exc
    root = tree.getroot()

    data: dict[str, Any] = {}
    company: dict[str, Any] = {}
    mapped, unmapped = 0, []

    for elem in root.iter():
        # Lokaler Tag-Name ohne Namespace
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        # Stammdaten (ESEF-Entity-Informationen)
        if local in ("EntityRegisteredName", "NameOfReportingEntity"):
            company["name"] = (elem.text or "").strip()
            continue
        if local in ("IdentifierOfEntity", "EntityIdentifier", "LegalEntityIdentifier"):
            company["lei"] = (elem.text or "").strip()
            continue

        # Nur Fakten mit contextRef sind XBRL-Fakten
        if "contextRef" not in elem.attrib:
            continue

        if local in concept_map:
            value = _coerce_number(elem.text or "")
            if value is not None:
                _set_path(data, concept_map[local], value)
                mapped += 1
        else:
            unmapped.append(local)

    # Berichtsjahr aus Kontext extrahieren (endDate/instant)
    year = None
    for ctx in root.iter():
        loc = ctx.tag.split("}")[-1]
        if loc in ("endDate", "instant"):
            m = re.search(r"(\d{4})", ctx.text or "")
            if m:
                year = int(m.group(1))
                break
    if company:
        if year:
            company["reporting_year"] = year
        data["company"] = {**company, **data.get("company", {})}

    if mapped == 0:
        raise IngestionError(
            "Keine XBRL-Fakten auf bekannte ESRS-Konzepte gemappt. "
            "Pruefe das Konzept-Mapping (XBRL_CONCEPT_MAP) oder das Instanzdokument."
        )

    data["_xbrl_meta"] = {
        "mapped_facts": mapped,
        "unmapped_concepts": sorted(set(unmapped))[:20],
    }
    return data


class DataIngestionAgent:
    """Schicht-2-Komponente: laedt und normalisiert heterogene Datenquellen.

    Unterstuetzte Formate: json | csv | xbrl/xml | txt (Freitext via LLM).
    Bei source_type='auto' wird das Format anhand der Dateiendung erkannt.
    """

    SUPPORTED_TYPES = ("json", "csv", "xbrl", "xml", "txt", "text")

    def __init__(self, llm=None) -> None:
        self.llm = llm

    def ingest(self, source: str | Path, source_type: str = "auto") -> dict:
        """Laedt Daten aus der Quelle und gibt ein normalisiertes Dict zurueck."""
        path = Path(source)
        if not path.exists():
            raise IngestionError(f"Quelldatei nicht gefunden: {path}")

        if source_type == "auto":
            source_type = path.suffix.lstrip(".").lower()
            if source_type in ("", "txt"):
                source_type = "text"

        if source_type == "json":
            data = _ingest_json(path)
        elif source_type == "csv":
            data = _ingest_csv(path)
        elif source_type in ("xbrl", "xml"):
            data = _ingest_xbrl(path)
        elif source_type in ("txt", "text"):
            text = path.read_text(encoding="utf-8")
            data = _ingest_text(text, self.llm, company_hint=path.stem)
        else:
            raise IngestionError(
                f"Unbekannter Quellentyp: '{source_type}'. "
                f"Unterstuetzt: {self.SUPPORTED_TYPES}"
            )

        data["_source"] = {"file": str(path), "type": source_type}
        return data

    def ingest_text_string(self, text: str, company_hint: str = "") -> dict:
        """Direkte Freitext-Ingestion ohne Datei (fuer Streamlit-Texteingabe)."""
        return _ingest_text(text, self.llm, company_hint)
