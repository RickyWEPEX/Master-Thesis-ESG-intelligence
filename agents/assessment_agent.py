"""Assessment & Calculation Module (Schicht 4 der 5-Schichten-Architektur).

Bewertet extrahierte ESRS-E1-KPIs gegen Sektorbenchmarks, berechnet abgeleitete
Kennzahlen und generiert Interpretationstexte fuer den ESG-Lagebericht.

Gemaess Thesis-Anforderungen:
- FA-5.5: Datenherkunft und Generierungslogik dokumentiert (Explainability)
- NFA-1.1: Nachvollziehbare Begruendungen fuer Fachexperten
- H2d: SHAP-/Benchmarking-basierte Nachvollziehbarkeit
- Benchmark-Quelle: data/benchmarks/sector_benchmarks.json
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agents.base import BaseAgent, ExtractedDatapoint
from utils.config_loader import get_by_path, resolve

_BENCHMARK_PATH = "data/benchmarks/sector_benchmarks.json"


@dataclass
class KPIBewertung:
    """Bewertung eines einzelnen KPIs mit Sektorvergleich und Interpretation."""
    dp_id: str
    name_de: str
    wert: float | None
    einheit: str
    ampel: str          # GRUEN | GELB | ROT | NEUTRAL
    sektor_p50: float | None
    abweichung_prozent: float | None   # positiv = besser als Median
    interpretation: str
    empfehlung: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AssessmentErgebnis:
    """Vollstaendiges Bewertungsergebnis fuer den ESG-Lagebericht."""
    unternehmensname: str
    berichtsjahr: int
    gesamtampel: str
    kpi_bewertungen: list[KPIBewertung] = field(default_factory=list)
    abgeleitete_kennzahlen: dict = field(default_factory=dict)
    staerken: list[str] = field(default_factory=list)
    schwaechen: list[str] = field(default_factory=list)
    risiken: list[str] = field(default_factory=list)
    chancen: list[str] = field(default_factory=list)
    handlungsempfehlungen: list[str] = field(default_factory=list)
    lagebericht_abschnitte: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _ampel(wert: float | None, schwelle_gruen: float | None,
           schwelle_gelb: float | None, hoeher_besser: bool = True) -> str:
    """Bestimmt Ampelfarbe. hoeher_besser=True: groesser = GRUEN."""
    if wert is None or schwelle_gruen is None:
        return "NEUTRAL"
    if hoeher_besser:
        if wert >= schwelle_gruen:
            return "GRUEN"
        if schwelle_gelb is not None and wert >= schwelle_gelb:
            return "GELB"
        return "ROT"
    else:
        if wert <= schwelle_gruen:
            return "GRUEN"
        if schwelle_gelb is not None and wert <= schwelle_gelb:
            return "GELB"
        return "ROT"


def _abweichung(wert: float | None, p50: float | None,
                hoeher_besser: bool = True) -> float | None:
    if wert is None or p50 is None or p50 == 0:
        return None
    diff = (wert - p50) / abs(p50) * 100
    return round(diff if hoeher_besser else -diff, 1)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)


class AssessmentAgent(BaseAgent):
    """Schicht-4-Agent: Bewertet KPIs und generiert Interpretationstext."""

    name = "AssessmentAgent"

    def __init__(self, audit, llm=None) -> None:
        super().__init__(audit)
        self.llm = llm
        benchmark_path = resolve(_BENCHMARK_PATH)
        if benchmark_path.exists():
            with open(benchmark_path, "r", encoding="utf-8") as fh:
                self._benchmarks = json.load(fh).get("benchmarks", {})
        else:
            self._benchmarks = {}
            self._log("benchmark_nicht_gefunden", {"path": str(benchmark_path)})

    def run(self, company_data: dict, extracted: list[ExtractedDatapoint],
            compliance) -> AssessmentErgebnis:
        self._log("assessment_started")
        company = company_data.get("company", {})
        name = company.get("name", "n/a")
        year = company.get("reporting_year", 2025)
        fte = company.get("employees_fte", 1)
        revenue = company.get("revenue_mio_eur", 1)

        ex = {e.id: e for e in extracted}

        # -- Abgeleitete Kennzahlen berechnen -----------------------------------
        scope_1 = get_by_path(company_data, "emissions.scope_1_tco2e") or 0
        scope_2_market = get_by_path(company_data, "emissions.scope_2_market_tco2e") or 0
        scope_3 = get_by_path(company_data, "emissions.scope_3_total_tco2e") or 0
        total_market = get_by_path(company_data, "emissions.total_ghg_market_tco2e") or 0
        cat15 = get_by_path(company_data, "emissions.scope_3_categories.cat_15_investments") or 0
        renewable_pct = get_by_path(company_data, "energy.renewable_share_percent") or 0
        ghg_intensity = get_by_path(company_data, "intensity.ghg_intensity_per_revenue") or 0
        int_carbon = get_by_path(company_data, "carbon_pricing.internal_carbon_price_eur_per_tco2e") or 0
        assets_risk_pct = get_by_path(company_data, "financial_effects.assets_at_physical_risk_percent") or 0
        reduction_target = get_by_path(company_data, "targets.reduction_target_percent") or 0
        net_zero = get_by_path(company_data, "targets.net_zero_year") or 0

        scope_1_per_fte = round(scope_1 / max(fte, 1), 2)
        scope_12_market_per_fte = round((scope_1 + scope_2_market) / max(fte, 1), 2)
        financed_share = round(cat15 / max(scope_3, 1) * 100, 1) if scope_3 else 0
        energy_intensity = get_by_path(company_data, "energy.energy_intensity_mwh_per_mio_eur") or 0

        abgeleitete = {
            "scope_1_per_fte": scope_1_per_fte,
            "scope_12_market_per_fte": scope_12_market_per_fte,
            "financed_emissions_share_scope3_pct": financed_share,
            "total_ghg_market_tco2e": total_market,
        }

        # -- KPI-Bewertungen ---------------------------------------------------
        bewertungen: list[KPIBewertung] = []

        # 1. THG-Intensitaet
        bm = self._benchmarks.get("ghg_intensity_per_revenue_tco2e_mio_eur", {})
        a = _ampel(ghg_intensity, bm.get("p25"), bm.get("p50"), hoeher_besser=False)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-023", name_de="THG-Intensitaet je Nettoumsatz",
            wert=ghg_intensity, einheit="tCO2e/Mio. EUR",
            ampel=a, sektor_p50=bm.get("p50"),
            abweichung_prozent=_abweichung(ghg_intensity, bm.get("p50"), hoeher_besser=False),
            interpretation=self._interpretiere_ghg_intensitaet(ghg_intensity, bm, name),
            empfehlung=self._empfehlung_ghg_intensitaet(a),
        ))

        # 2. Scope-1-Emissionen je FTE
        bm2 = self._benchmarks.get("scope_1_per_employee_tco2e", {})
        a2 = _ampel(scope_1_per_fte, bm2.get("ampel", {}).get("gruen"),
                    bm2.get("ampel", {}).get("gelb"), hoeher_besser=False)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-001", name_de="Scope-1-Emissionen je FTE",
            wert=scope_1_per_fte, einheit="tCO2e/FTE",
            ampel=a2, sektor_p50=bm2.get("p50"),
            abweichung_prozent=_abweichung(scope_1_per_fte, bm2.get("p50"), hoeher_besser=False),
            interpretation=(
                f"Die spezifischen Scope-1-Emissionen betragen {_fmt(scope_1_per_fte)} tCO2e je FTE "
                f"(Sektormedian: {_fmt(bm2.get('p50', 0))} tCO2e/FTE). "
                + ("Unterdurchschnittlich — gute Effizienz im Betrieb." if a2 == "GRUEN"
                   else "Mittleres Niveau — Potenzial bei Gebaeude und Fuhrpark." if a2 == "GELB"
                   else "Ueberdurchschnittlich — Dekarbonisierung des Eigenbetriebs prioritaer.")
            ),
            empfehlung=(
                "Weiter optimieren (Gebaeude-Energieeffizienz, Fuhrparkelektrifizierung)." if a2 != "GRUEN"
                else "Niveau halten; Best Practices dokumentieren."
            ),
        ))

        # 3. Erneuerbare Energie
        bm3 = self._benchmarks.get("renewable_share_percent", {})
        a3 = _ampel(renewable_pct, bm3.get("ampel", {}).get("gruen"),
                    bm3.get("ampel", {}).get("gelb"), hoeher_besser=True)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-017", name_de="Anteil erneuerbarer Energie",
            wert=renewable_pct, einheit="%",
            ampel=a3, sektor_p50=bm3.get("p50"),
            abweichung_prozent=_abweichung(renewable_pct, bm3.get("p50"), hoeher_besser=True),
            interpretation=self._interpretiere_erneuerbare(renewable_pct, bm3),
            empfehlung=bm3.get(f"interpretation_{a3.lower()}", "Ausbau erneuerbarer Energien fortsetzen."),
        ))

        # 4. Reduktionsziel
        bm4 = self._benchmarks.get("reduction_target_percent", {})
        a4 = _ampel(reduction_target, bm4.get("ampel", {}).get("gruen"),
                    bm4.get("ampel", {}).get("gelb"), hoeher_besser=True)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-021", name_de="THG-Reduktionsziel (Brutto %)",
            wert=reduction_target, einheit="%",
            ampel=a4, sektor_p50=bm4.get("p50"),
            abweichung_prozent=_abweichung(reduction_target, bm4.get("p50"), hoeher_besser=True),
            interpretation=self._interpretiere_reduktionsziel(reduction_target, net_zero, bm4),
            empfehlung=bm4.get(f"interpretation_{a4.lower()}", ""),
        ))

        # 5. Interner CO2-Preis
        bm5 = self._benchmarks.get("internal_carbon_price_eur", {})
        a5 = _ampel(int_carbon, bm5.get("ampel", {}).get("gruen"),
                    bm5.get("ampel", {}).get("gelb"), hoeher_besser=True)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-026", name_de="Interner CO2-Preis",
            wert=int_carbon, einheit="EUR/tCO2e",
            ampel=a5, sektor_p50=bm5.get("p50"),
            abweichung_prozent=_abweichung(int_carbon, bm5.get("p50"), hoeher_besser=True),
            interpretation=(
                f"Der interne CO2-Preis von {_fmt(int_carbon)} EUR/tCO2e liegt "
                + ("deutlich ueber dem Sektordurchschnitt ({} EUR). Starkes Signal fuer Investitionssteuerung.".format(_fmt(bm5.get("p50", 0))) if a5 == "GRUEN"
                   else "im mittleren Bereich ({} EUR Median). Wirkung auf Kreditentscheidungen begrenzt.".format(_fmt(bm5.get("p50", 0))) if a5 == "GELB"
                   else "unter dem Sektordurchschnitt. Lenkungswirkung gering.")
            ),
            empfehlung=(
                "CO2-Preis auf mind. 75 EUR/tCO2e anheben (SBTi-Empfehlung)." if a5 != "GRUEN"
                else "Preisniveau beibehalten und regelmaessig an EU-ETS anpassen."
            ),
        ))

        # 6. Physisches Risiko
        bm6 = self._benchmarks.get("assets_at_physical_risk_percent", {})
        a6 = _ampel(assets_risk_pct, bm6.get("ampel", {}).get("gruen"),
                    bm6.get("ampel", {}).get("gelb"), hoeher_besser=False)
        bewertungen.append(KPIBewertung(
            dp_id="E1-DP-028", name_de="Anteil physisch risikoexponierter Vermoegenswerte",
            wert=assets_risk_pct, einheit="%",
            ampel=a6, sektor_p50=bm6.get("p50"),
            abweichung_prozent=_abweichung(assets_risk_pct, bm6.get("p50"), hoeher_besser=False),
            interpretation=bm6.get(f"interpretation_{a6.lower()}",
                                   f"{_fmt(assets_risk_pct)}% der Vermoegenswerte physisch risikoexponiert."),
            empfehlung=(
                "Risikokonzentration in klimavulnerablen Sektoren reduzieren." if a6 == "ROT"
                else "Regelmaessige Klimarisikoanalysen durchfuehren." if a6 == "GELB"
                else "Niveau halten; Szenarioanalysen aktualisieren."
            ),
        ))

        # -- E2-G1: Bewertungen fuer alle weiteren Standards -------------------
        self._bewerte_weitere_standards(bewertungen, company_data)

        # -- Staerken, Schwaechen, Risiken, Chancen ----------------------------
        staerken, schwaechen, risiken, chancen = self._swot(
            bewertungen, financed_share, scope_3, cat15, company_data)

        # -- Gesamtampel (E1-spezifisch: Klimaperformance) ---------------------
        # Nur E1-KPIs fuer die Klimaampel; E2-G1 haben eigene Standard-Ampeln
        e1_bew = [b for b in bewertungen if b.dp_id.startswith("E1-")]
        e1_counts = {"GRUEN": 0, "GELB": 0, "ROT": 0}
        for b in e1_bew:
            if b.ampel in e1_counts:
                e1_counts[b.ampel] += 1
        n_e1 = len(e1_bew)
        if n_e1 == 0:
            gesamt = "NEUTRAL"
        elif e1_counts["ROT"] / max(n_e1, 1) >= 0.30:
            gesamt = "ROT"
        elif e1_counts["GRUEN"] / max(n_e1, 1) >= 0.70:
            gesamt = "GRUEN"
        else:
            gesamt = "GELB"

        # -- Lagebericht-Abschnitte generieren ---------------------------------
        abschnitte = self._lagebericht_abschnitte(
            company_data, bewertungen, abgeleitete, financed_share,
            scope_1, scope_2_market, scope_3, cat15, renewable_pct,
            reduction_target, net_zero, int_carbon, assets_risk_pct,
            ghg_intensity, name, year, fte, revenue,
        )

        # -- Handlungsempfehlungen priorisieren --------------------------------
        empfehlungen = self._priorisierte_empfehlungen(bewertungen, financed_share)

        ergebnis = AssessmentErgebnis(
            unternehmensname=name,
            berichtsjahr=year,
            gesamtampel=gesamt,
            kpi_bewertungen=bewertungen,
            abgeleitete_kennzahlen=abgeleitete,
            staerken=staerken,
            schwaechen=schwaechen,
            risiken=risiken,
            chancen=chancen,
            handlungsempfehlungen=empfehlungen,
            lagebericht_abschnitte=abschnitte,
        )

        self._log("assessment_completed", {
            "gesamtampel": gesamt,
            "kpi_anzahl": len(bewertungen),
            "gruen": e1_counts["GRUEN"],
            "gelb": e1_counts["GELB"],
            "rot": e1_counts["ROT"],
        })
        return ergebnis

    # -- Private Interpretationsmethoden --------------------------------------

    def _interpretiere_ghg_intensitaet(self, wert: float, bm: dict, name: str) -> str:
        p25, p50, p75 = bm.get("p25", 550), bm.get("p50", 1100), bm.get("p75", 2200)
        if wert <= p25:
            lage = f"deutlich unter dem Sektordurchschnitt ({_fmt(p50)} tCO2e/Mio. EUR) im unteren Quartil"
            bewertung = "sehr gut positioniert fuer regulatorische Anforderungen"
        elif wert <= p50:
            lage = f"unter dem Sektordurchschnitt ({_fmt(p50)} tCO2e/Mio. EUR)"
            bewertung = "gut positioniert; weiteres Optimierungspotenzial vorhanden"
        elif wert <= p75:
            lage = f"leicht ueber dem Sektordurchschnitt ({_fmt(p50)} tCO2e/Mio. EUR)"
            bewertung = "Handlungsbedarf, insbesondere bei Portfolioausrichtung"
        else:
            lage = f"deutlich ueber dem Sektordurchschnitt ({_fmt(p50)} tCO2e/Mio. EUR, oberes Quartil)"
            bewertung = "erheblicher Transformationsbedarf im Kredit- und Investitionsportfolio"
        return (
            f"Die THG-Intensitaet von {_fmt(wert)} tCO2e/Mio. EUR liegt {lage}. "
            f"Das Institut ist {bewertung}. Die Intensitaet wird massgeblich durch "
            f"Scope-3-Kategorie-15-Emissionen (finanzierte Emissionen) getrieben."
        )

    def _empfehlung_ghg_intensitaet(self, ampel: str) -> str:
        mapping = {
            "GRUEN": "Intensitaet weiter senken durch Portfolioausrichtung auf klimavertraegliche Sektoren.",
            "GELB": "Kreditportfolio systematisch dekarbonisieren; Sektor-Ausschlusskriterien schaerfen.",
            "ROT": "Sofortmassnahmen: Klimarisikofilter bei Kreditvergabe einführen; PCAF-Methodik implementieren.",
        }
        return mapping.get(ampel, "")

    def _interpretiere_erneuerbare(self, pct: float, bm: dict) -> str:
        p50 = bm.get("p50", 45)
        if pct >= 80:
            return (f"Mit {_fmt(pct)}% erneuerbarerm Strom liegt das Institut im fuehrenden Segment "
                    f"(Sektormedian: {_fmt(p50)}%). Dekarbonisierung der Eigenenergie weitgehend abgeschlossen.")
        elif pct >= p50:
            return (f"Der Anteil erneuerbarer Energie ({_fmt(pct)}%) entspricht dem Sektordurchschnitt "
                    f"({_fmt(p50)}%). Das Ziel von 100% bis 2027 ist ambitioniert und wuerde in die "
                    f"erste Quartile des Sektors fuehren.")
        else:
            return (f"Mit {_fmt(pct)}% liegt der Anteil erneuerbarer Energie unter dem Sektordurchschnitt "
                    f"({_fmt(p50)}%). Beschleunigter Ausbau im Rahmen der Energiestrategie erforderlich.")

    def _interpretiere_reduktionsziel(self, target_pct: float, net_zero: int, bm: dict) -> str:
        p50 = bm.get("p50", 38)
        nz_str = f" Netto-Null bis {int(net_zero)} ist fuer den Finanzsektor sehr ambitioniert." if net_zero else ""
        vergleich = ("uebertrifft den Sektordurchschnitt" if target_pct > p50
                     else "liegt im Sektordurchschnitt" if target_pct >= p50 * 0.9
                     else "liegt unter dem Sektordurchschnitt")
        sbti = " Das Ziel ist kompatibel mit dem 1,5-Grad-Pfad (SBTi-Kriterium: >50%)." if target_pct >= 50 else ""
        return (f"Das THG-Reduktionsziel von {_fmt(target_pct)}% bis {2030} {vergleich} "
                f"({_fmt(p50)}% Median).{sbti}{nz_str}")

    def _bewerte_weitere_standards(
        self, bewertungen: list, company_data: dict
    ) -> None:
        """Bewertet KPIs fuer E2-G1 gegen Sektorbenchmarks.

        Konfigurationstabelle: (dp_id, data_path, bm_key, name_de, einheit, hoeher_besser)
        Verwendet generische Benchmark-Interpretation; fuegt Bewertungen in-place hinzu.
        """
        _KPI_KONFIG = [
            # E2 Umweltverschmutzung
            ("E2-DP-001", "pollution.air_emissions_nox_kg",
             "air_emissions_nox_kg", "NOx-Emissionen (Luft)", "kg", False),
            ("E2-DP-005", "pollution.hazardous_waste_tonnes",
             "hazardous_waste_tonnes", "Gefaehrliche Abfaelle", "t", False),
            # E3 Wasser
            ("E3-DP-004", "water.water_intensity_m3_per_fte",
             "water_intensity_m3_per_fte", "Wasserverbrauch je FTE", "m3/FTE", False),
            ("E3-DP-005", "water.water_stress_area_withdrawal_percent",
             "water_stress_area_withdrawal_percent", "Wasserentnahme in Stressgebieten", "%", False),
            # E5 Ressourcen
            ("E5-DP-002", "resources.recycling_rate_percent",
             "recycling_rate_percent", "Recyclingquote", "%", True),
            ("E5-DP-003", "resources.paper_consumption_kg_per_fte",
             "paper_consumption_kg_per_fte", "Papierverbrauch je FTE", "kg/FTE", False),
            # S1 Belegschaft
            ("S1-DP-002", "social_own_workforce.gender_pay_gap_percent",
             "gender_pay_gap_percent", "Gender Pay Gap", "%", False),
            ("S1-DP-003", "social_own_workforce.injury_rate_per_1000_fte",
             "injury_rate_per_1000_fte", "Verletzungsrate je 1.000 FTE", "Faelle/1000 FTE", False),
            ("S1-DP-004", "social_own_workforce.training_hours_per_fte",
             "training_hours_per_fte", "Schulungsstunden je FTE", "h/FTE", True),
            ("S1-DP-006", "social_own_workforce.female_leadership_percent",
             "female_leadership_percent", "Frauenanteil Fuehrung", "%", True),
            ("S1-DP-007", "social_own_workforce.collective_bargaining_coverage_percent",
             "collective_bargaining_coverage_percent", "Tarifbindungsquote", "%", True),
            # S2 Wertschoepfungskette
            ("S2-DP-003", "social_value_chain.high_risk_suppliers_percent",
             "high_risk_suppliers_percent", "Hochrisikolieferanten-Anteil", "%", False),
            ("S2-DP-002", "social_value_chain.supplier_audits_count",
             "supplier_audits_count", "Lieferantenaudits je Jahr", "Audits", True),
            # S4 Verbraucher
            ("S4-DP-001", "consumers.customer_complaints_per_1000",
             "customer_complaints_per_1000", "Kundenbeschwerden je 1.000", "Beschwerden/1000", False),
            ("S4-DP-004", "consumers.customer_satisfaction_score",
             "customer_satisfaction_score", "Kundenzufriedenheitsindex", "Punkte (0-100)", True),
            # G1 Governance
            ("G1-DP-002", "governance.anti_corruption_training_percent",
             "anti_corruption_training_percent", "Antikorruptionstraining-Abdeckung", "%", True),
            ("G1-DP-005", "governance.board_independence_percent",
             "board_independence_percent", "Unabhaengigkeit des Aufsichtsrats", "%", True),
            ("G1-DP-006", "governance.women_on_board_percent",
             "women_on_board_percent", "Frauenanteil im Aufsichtsrat", "%", True),
        ]

        for dp_id, data_path, bm_key, name_de, einheit, hoeher_besser in _KPI_KONFIG:
            wert = get_by_path(company_data, data_path)
            bm = self._benchmarks.get(bm_key, {})

            # Fehlende Daten: explizit als NEUTRAL kennzeichnen statt still ueberspringen
            if wert is None or not isinstance(wert, (int, float)):
                bewertungen.append(KPIBewertung(
                    dp_id=dp_id,
                    name_de=name_de,
                    wert=None,
                    einheit=einheit,
                    ampel="NEUTRAL",
                    sektor_p50=bm.get("p50"),
                    abweichung_prozent=None,
                    interpretation=(
                        f"Datenpunkt nicht vorhanden — keine belastbare Aussage moeglich. "
                        f"Der Wert '{data_path}' fehlt in den Eingabedaten. "
                        f"Sektormedian: {_fmt(bm.get('p50'))} {einheit} (zur Referenz)."
                        if bm.get("p50") else
                        f"Datenpunkt nicht vorhanden — keine belastbare Aussage moeglich. "
                        f"Bitte '{data_path}' in den Unternehmensdaten erganzen."
                    ),
                    empfehlung=f"Datenpunkt '{name_de}' erheben und im naechsten Berichtszyklus offenlegen.",
                ))
                continue

            wert = float(wert)
            if not bm:
                continue

            a_cfg = bm.get("ampel", {})
            ampel = _ampel(wert, a_cfg.get("gruen"), a_cfg.get("gelb"), hoeher_besser)

            # Interpretation: aus Benchmark-JSON oder generisch
            interp_key = f"interpretation_{ampel.lower()}"
            if interp_key in bm:
                interp = bm[interp_key]
            else:
                p50 = bm.get("p50")
                vergleich = ""
                if p50 is not None:
                    if hoeher_besser:
                        vergleich = ("ueberdurchschnittlich" if wert >= p50
                                     else "unterdurchschnittlich")
                    else:
                        vergleich = ("guenstig (unter Median)" if wert <= p50
                                     else "erhoehter Handlungsbedarf (ueber Median)")
                interp = (
                    f"{name_de}: {_fmt(wert)} {einheit} "
                    f"(Sektormedian: {_fmt(p50)} {einheit}). {vergleich.capitalize()}."
                    if p50 else f"{name_de}: {_fmt(wert)} {einheit}."
                )

            # Empfehlung
            if ampel == "ROT":
                empf = bm.get("interpretation_rot", f"{name_de} verbessern — unter Sektormedian.")
            elif ampel == "GELB":
                empf = bm.get("interpretation_gelb", f"{name_de} weiter optimieren.")
            else:
                empf = "Niveau halten und in naechstem Berichtszyklus dokumentieren."

            p50_val = bm.get("p50")
            abw = _abweichung(wert, p50_val, hoeher_besser) if p50_val else None

            bewertungen.append(KPIBewertung(
                dp_id=dp_id,
                name_de=name_de,
                wert=wert,
                einheit=einheit,
                ampel=ampel,
                sektor_p50=p50_val,
                abweichung_prozent=abw,
                interpretation=interp,
                empfehlung=empf,
            ))

    def _swot(self, bewertungen, financed_share, scope_3, cat15, company_data):
        staerken, schwaechen, risiken, chancen = [], [], [], []
        gruen_dps = [b for b in bewertungen if b.ampel == "GRUEN"]
        rot_dps = [b for b in bewertungen if b.ampel == "ROT"]
        gelb_dps = [b for b in bewertungen if b.ampel == "GELB"]

        for b in gruen_dps:
            staerken.append(f"{b.name_de}: {_fmt(b.wert)} {b.einheit} — ueberdurchschnittlich.")
        for b in rot_dps:
            schwaechen.append(f"{b.name_de}: {_fmt(b.wert)} {b.einheit} — Handlungsbedarf.")

        if financed_share > 85:
            risiken.append(
                f"Finanzierte Emissionen (Scope 3 Kat. 15) dominieren mit {_fmt(financed_share)}% "
                f"der Scope-3-Gesamtemissionen. Haupthebel liegt bei Portfolioausrichtung."
            )
        risiken.append("Regulatorisches Risiko: Verschaerfung CSRD/MaRisk-Novelle 9 ab 2026.")
        risiken.append("Transitionsrisiko: CO2-Bepreisung und Marktpraeferenzwandel koennen Portfolioqualitaet mindern.")

        gar = get_by_path(company_data, "financial_effects.green_asset_ratio_percent") or 0
        gfv = get_by_path(company_data, "financial_effects.green_financing_volume_mio_eur") or 0
        if gar > 0:
            chancen.append(f"Green Asset Ratio von {_fmt(gar)}% zeigt Wachstumspotenzial im nachhaltigen Kreditgeschaeft.")
        if gfv > 0:
            chancen.append(f"Green-Financing-Volumen von {_fmt(gfv)} Mio. EUR bietet Wachstumspfad.")
        chancen.append("Steigende Nachfrage nach gruenen Finanzprodukten und ESG-Beratung.")

        return staerken, schwaechen, risiken, chancen

    def _priorisierte_empfehlungen(self, bewertungen, financed_share) -> list[str]:
        empfehlungen = []
        rot_b = [b for b in bewertungen if b.ampel == "ROT"]
        gelb_b = [b for b in bewertungen if b.ampel == "GELB"]
        for b in rot_b:
            empfehlungen.append(f"[PRIORITAET HOCH] {b.name_de}: {b.empfehlung}")
        for b in gelb_b:
            empfehlungen.append(f"[PRIORITAET MITTEL] {b.name_de}: {b.empfehlung}")
        if financed_share > 85:
            empfehlungen.insert(0,
                "[PRIORITAET HOCH] Finanzierte Emissionen: PCAF-Standard implementieren; "
                "Sektorstrategie fuer kohlenstoffintensive Portfoliosegmente entwickeln."
            )
        empfehlungen.append(
            "[PRIORITAET MITTEL] ESRS-Reporting: Datenpunkte zu Green Asset Ratio und "
            "finanzierten Emissionen fuer naechsten Berichtszyklus quantifizieren."
        )
        return empfehlungen

    def _lagebericht_abschnitte(
        self, company_data, bewertungen, abgeleitete,
        financed_share, scope_1, scope_2_market, scope_3, cat15,
        renewable_pct, reduction_target, net_zero, int_carbon, assets_risk_pct,
        ghg_intensity, name, year, fte, revenue,
    ) -> dict:
        """Erzeugt narrative Lagebericht-Abschnitte pro Themenfeld."""

        # Ampelfarben fuer schnellen Zugriff
        ampel_map = {b.dp_id: b.ampel for b in bewertungen}
        ghg_ampel = ampel_map.get("E1-DP-023", "NEUTRAL")
        ren_ampel = ampel_map.get("E1-DP-017", "NEUTRAL")
        red_ampel = ampel_map.get("E1-DP-021", "NEUTRAL")

        scope_12_market = scope_1 + scope_2_market
        scope_3_share = round(scope_3 / max(scope_1 + scope_2_market + scope_3, 1) * 100, 1)

        abschnitte = {}

        # 1. Klimastrategie und Governance
        abschnitte["klimastrategie"] = (
            f"Die {name} verfolgt eine integrierte Klimastrategie, die auf das Pariser "
            f"Abkommen ausgerichtet ist. Im Berichtsjahr {year} wurden die strategischen "
            f"Klimaziele in den Rahmen des Design Science Research-Prototyps eingebettet und "
            f"erstmals vollstaendig nach ESRS E1 (Amended Exposure Drafts, Juli 2025) erfasst. "
            f"Die Klimastrategie ist vom Vorstand verabschiedet und in der konzernweiten "
            f"Nachhaltigkeitsrichtlinie verankert. Verantwortlichkeiten, Sektor-Ausschlusskriterien "
            f"sowie Engagement-Prozesse fuer Portfoliounternehmen sind definiert."
        )

        # 2. THG-Emissionen
        reduction_hint = ""
        base_year = get_by_path(company_data, "targets.base_year")
        if base_year:
            reduction_hint = (
                f" Seit dem Basisjahr {int(base_year)} wurden die Scope-1- und Scope-2-Emissionen "
                f"(marktbasiert) um {_fmt(abgeleitete.get('scope_12_reduction_vs_base', 0))}% reduziert."
            )

        abschnitte["thg_emissionen"] = (
            f"Im Berichtsjahr {year} belaufen sich die Gesamtemissionen der {name} "
            f"(marktbasiert) auf {_fmt(scope_1 + scope_2_market + scope_3):} tCO2e, "
            f"wovon Scope 1 {_fmt(scope_1)} tCO2e ({round(scope_1 / max(scope_1 + scope_2_market + scope_3, 1) * 100, 1)}%), "
            f"Scope 2 (marktbasiert) {_fmt(scope_2_market)} tCO2e sowie "
            f"Scope 3 insgesamt {_fmt(scope_3)} tCO2e ({scope_3_share}%) ausmachen. "
            f"Die THG-Intensitaet betraegt {_fmt(ghg_intensity)} tCO2e/Mio. EUR Nettoumsatz "
            f"({'ueberdurchschnittlich — Handlungsbedarf' if ghg_ampel == 'ROT' else 'im Sektordurchschnitt' if ghg_ampel == 'GELB' else 'unterdurchschnittlich — gut positioniert'})."
            f" Die finanzierte Emissionen (Scope 3 Kategorie 15) betragen {_fmt(cat15)} tCO2e "
            f"und repraesentieren {_fmt(financed_share)}% der Scope-3-Gesamtemissionen "
            f"— typisch fuer Finanzinstitute und Kernhebel der Dekarbonisierungsstrategie."
            f"{reduction_hint}"
        )

        # 3. Energie
        total_mwh = get_by_path(company_data, "energy.total_consumption_mwh") or 0
        fossil_mwh = get_by_path(company_data, "energy.fossil_mwh") or 0
        energy_intensity = get_by_path(company_data, "energy.energy_intensity_mwh_per_mio_eur") or 0
        own_gen = get_by_path(company_data, "energy.own_renewable_generation_mwh") or 0
        savings = get_by_path(company_data, "energy.energy_savings_mwh") or 0

        abschnitte["energie"] = (
            f"Der Gesamtenergieverbrauch der {name} betraegt {_fmt(total_mwh)} MWh, "
            f"wovon {_fmt(fossil_mwh)} MWh ({round(fossil_mwh / max(total_mwh, 1) * 100, 1)}%) "
            f"aus fossilen Quellen stammen. Der Anteil erneuerbarer Energie liegt bei "
            f"{_fmt(renewable_pct)}% "
            f"({'ueberdurchschnittlich' if ren_ampel == 'GRUEN' else 'im Durchschnitt' if ren_ampel == 'GELB' else 'unterdurchschnittlich'}). "
            f"Die Energieintensitaet betraegt {_fmt(energy_intensity)} MWh/Mio. EUR. "
            f"Aus eigener Erzeugung wurden {_fmt(own_gen)} MWh erneuerbare Energie produziert; "
            f"durch Effizienzmasnahmen konnten {_fmt(savings)} MWh eingespart werden. "
            f"Das Ziel, bis 2027 den Strombezug vollstaendig auf erneuerbare Quellen umzustellen, "
            f"wuerde den erneuerbaren Anteil auf annaehernd 100% anheben und die "
            f"Scope-2-Emissionen auf nahe null reduzieren."
        )

        # 4. Klimaziele
        abschnitte["klimaziele"] = (
            f"Die {name} verfolgt ein verbindliches THG-Reduktionsziel von {_fmt(reduction_target)}% "
            f"bis {get_by_path(company_data, 'targets.target_year') or 2030} "
            f"(Basisjahr: {get_by_path(company_data, 'targets.base_year') or 2019}). "
            f"Dies ist "
            f"{'kompatibel mit dem 1,5-Grad-Pfad des Pariser Abkommens (SBTi-Kriterium: >50%)' if reduction_target >= 50 else 'unter dem SBTi-1,5-Grad-Kriterium (>50%); Zielverschaerfung empfohlen'}. "
            f"Das langfristige Netto-Null-Ziel ist fuer {int(net_zero) if net_zero else 'nicht festgelegt'} terminiert "
            f"({'ambitioniert — fuehrendes Quartil des Sektors' if net_zero and net_zero <= 2040 else 'im Sektor-Mainstream'}). "
            f"Der interne CO2-Preis von {_fmt(int_carbon)} EUR/tCO2e "
            f"{'uebertrifft' if int_carbon >= 75 else 'liegt unter'} den SBTi-Empfehlungen (75 EUR/tCO2e) "
            f"und wird zur Steuerung von Investitionsentscheidungen eingesetzt."
        )

        # 5. Physische und transitorische Risiken
        trans_exp = get_by_path(company_data, "financial_effects.transition_risk_exposure_mio_eur") or 0
        abschnitte["klimarisiken"] = (
            f"Physische Klimarisiken betreffen {_fmt(assets_risk_pct)}% der Vermoegenswerte der {name} "
            f"(absolut: {_fmt(get_by_path(company_data, 'financial_effects.assets_at_physical_risk_mio_eur') or 0)} Mio. EUR), "
            f"insbesondere Immobiliensicherheiten in hochwassergefaehrdeten Regionen. "
            f"Dies liegt "
            f"{'unter dem Sektordurchschnitt (7% Median) — gut positioniert' if assets_risk_pct < 7 else 'im Sektordurchschnitt' if assets_risk_pct <= 9 else 'ueber dem Sektordurchschnitt — erhoehter Handlungsbedarf'}. "
            f"Das Transitionsrisikoexpositionsvolumen wird auf {_fmt(trans_exp)} Mio. EUR beziffert "
            f"und umfasst Kreditnehmer in potenziell kohlenstoffintensiven Sektoren, "
            f"die regulatorischen CO2-Kostenverschiebungen ausgesetzt sind."
        )

        # 6. Nachhaltige Finanzierung
        gar = get_by_path(company_data, "financial_effects.green_asset_ratio_percent") or 0
        gfv = get_by_path(company_data, "financial_effects.green_financing_volume_mio_eur") or 0
        abschnitte["nachhaltige_finanzierung"] = (
            f"Die Green Asset Ratio (GAR) der {name} betraegt aktuell {_fmt(gar)}%. "
            f"Das Green-Financing-Volumen (gruene Kredite, Anleihen, Beratungsleistungen) "
            f"belaeuft sich auf {_fmt(gfv)} Mio. EUR im Berichtsjahr {year}. "
            f"Das Institut positioniert sich als Transformationsbegleiter fuer Firmenkunden "
            f"auf dem Weg zur Klimaneutralitaet. "
            f"Eine Steigerung der GAR erfordert systematische Klassifizierung des Kreditportfolios "
            f"gemaess EU-Taxonomie-Verordnung sowie Ausbau des Green-Financing-Angebots."
        )

        # 7. Gesamtbewertung
        ampel_gruen = sum(1 for b in bewertungen if b.ampel == "GRUEN")
        ampel_rot = sum(1 for b in bewertungen if b.ampel == "ROT")
        abschnitte["gesamtbewertung"] = (
            f"Die {name} zeigt in der ESG-E1-Evaluation eine gemischte Performance: "
            f"{ampel_gruen} von {len(bewertungen)} KPIs werden positiv (gruen) bewertet, "
            f"{ampel_rot} weisen Handlungsbedarf (rot) auf. "
            f"Besondere Staerken liegen in "
            f"{', '.join([b.name_de for b in bewertungen if b.ampel == 'GRUEN'][:3]) or 'keiner Kategorie'}. "
            f"Der Haupthebel fuer die Dekarbonisierung liegt in der Portfolioausrichtung: "
            f"Finanzierte Emissionen (Scope 3 Kat. 15) repraesentieren {_fmt(financed_share)}% "
            f"der Gesamtemissionen und erfordern eine systematische Kreditportfolio-Strategie "
            f"auf Basis des PCAF-Standards. Das Framework wurde vollstaendig gemaess ESRS E1 "
            f"(Amended Exposure Drafts, Juli 2025) erstellt und automatisiert validiert."
        )

        return abschnitte
