"""Demo: So funktioniert ein echter LLM-API-Call im Prototyp.

Zeigt vollstaendig transparent:
1. Was an die Claude-API gesendet wird (System-Prompt + User-Prompt)
2. Was die API zurueckgibt (rohe JSON-Antwort)
3. Wie der Agent die Antwort verarbeitet

Aufruf: python demo_api_call.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv()

from core.llm_client import ClaudeClient, LLMUnavailableError
from utils.config_loader import load_json, load_settings, load_yaml

# ===========================================================================
# SCHRITT 1: Unternehmensdaten in Berichtstext umwandeln
# (Das macht der DataExtractionAgent intern via _company_to_text())
# ===========================================================================
company_data = load_json("data/synthetic/synthetic_company_data.json")
company = company_data.get("company", {})
e = company_data.get("emissions", {})
en = company_data.get("energy", {})

report_text = f"""Unternehmen: {company.get('name')}
Sektor: {company.get('sector')}, Berichtsjahr: {company.get('reporting_year')}
Mitarbeiter (FTE): {company.get('employees_fte')}

=== THG-Emissionen ===
Scope 1: {e.get('scope_1_tco2e')} tCO2e
Scope 2 (marktbasiert): {e.get('scope_2_market_tco2e')} tCO2e
Scope 3 gesamt: {e.get('scope_3_total_tco2e')} tCO2e
THG gesamt (marktbasiert): {e.get('total_ghg_market_tco2e')} tCO2e

=== Energieverbrauch ===
Anteil erneuerbarer Energie: {en.get('renewable_share_percent')} %
Gesamtenergieverbrauch: {en.get('total_consumption_mwh')} MWh
"""

# ===========================================================================
# SCHRITT 2: Datenpunkt auswaehlen (z.B. Scope-1-Emissionen)
# ===========================================================================
catalog = load_yaml("config/esrs_e1_datapoints.yaml")
settings = load_settings()

# Beispiel: Scope-1-Datenpunkt
dp = next(d for d in catalog["datapoints"] if d["id"] == "E1-DP-001")

# ===========================================================================
# SCHRITT 3: Prompt zusammenbauen (genau was an die API geht)
# ===========================================================================
unit_hint = f" in {dp['unit']}" if dp.get("unit") else ""

SYSTEM_PROMPT = (
    "Du bist ein ESRS-E1-Extraktions-Assistent. Extrahiere Datenpunkte "
    "aus Nachhaltigkeitsberichten praezise. Antworte ausschliesslich im "
    "vorgegebenen JSON-Format, ohne Markdown-Formatierung."
)

USER_PROMPT = (
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

print("=" * 70)
print("DEMO: LLM-API-CALL IM ESG-AGENTEN-FRAMEWORK")
print("=" * 70)
print(f"\nDateipunkt: {dp['id']} — {dp['name_de']}")
print(f"Modell:     {settings['llm']['model']}")
print(f"Endpoint:   api.anthropic.com/v1/messages\n")

print("-" * 70)
print("SYSTEM-PROMPT (Rolle des Agenten):")
print("-" * 70)
print(SYSTEM_PROMPT)

print("\n" + "-" * 70)
print("USER-PROMPT (Berichtstext + Extraktionsaufgabe):")
print("-" * 70)
print(USER_PROMPT[:800] + "..." if len(USER_PROMPT) > 800 else USER_PROMPT)

# ===========================================================================
# SCHRITT 4: API-Call (wenn Key vorhanden)
# ===========================================================================
llm_cfg = settings.get("llm", {})
llm = ClaudeClient(
    model=llm_cfg.get("model", "claude-sonnet-4-6"),
    max_tokens=300,
    temperature=0.2,
)

print("\n" + "-" * 70)
if not llm.available:
    print("KEIN API-KEY GESETZT — simulierte Antwort:")
    raw_response = '{"value": 1250.5, "found": true, "confidence": 0.97, "reasoning": "Scope-1-Emissionen explizit als 1250.5 tCO2e angegeben."}'
else:
    print("API-CALL LAEUFT...")
    raw_response = llm.complete(system=SYSTEM_PROMPT, prompt=USER_PROMPT)

print("\nROHE API-ANTWORT (was Claude zurueckgibt):")
print("-" * 70)
print(raw_response)

# ===========================================================================
# SCHRITT 5: Verarbeitung der Antwort
# ===========================================================================
result = json.loads(raw_response.strip())
value = result.get("value")
found = bool(result.get("found", value is not None))
confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
if found and value is not None and dp["datatype"] == "numeric":
    try:
        value = float(value)
    except (ValueError, TypeError):
        confidence = max(0.0, confidence - 0.2)

print("\n" + "-" * 70)
print("VERARBEITETES ERGEBNIS (ExtractedDatapoint):")
print("-" * 70)
print(f"  id:          {dp['id']}")
print(f"  name_de:     {dp['name_de']}")
print(f"  value:       {value}")
print(f"  found:       {found}")
print(f"  confidence:  {confidence}")
print(f"  reasoning:   {result.get('reasoning', 'n/a')}")
print(f"  method:      llm_extraction")

print("\n" + "=" * 70)
print("ZUSAMMENFASSUNG:")
print("  - Das ist 1 von ~44 API-Calls (ein Call je Datenpunkt)")
print("  - Laufzeit je Call: ~2-5 Sekunden => ~44 Calls = ~120s Gesamt")
print("  - Deterministic-Backend: 0 Calls (nur Dict-Lookup)")
print("  - Assessment/Interpretation: 0 Calls (Benchmark-Vergleich)")
print("=" * 70)
