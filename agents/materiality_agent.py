"""Double Materiality Assessment Agent (ESRS 1 / IRO-1 / FA-3.2).

Fuehrt die doppelte Wesentlichkeitsanalyse durch (Impact + Financial Materiality)
gemaess ESRS 1, Kapitel 3. Ein Thema ist wesentlich, wenn mindestens eine
Dimension den Schwellenwert erreicht.

Zwei Betriebsmodi:
  1. Manuell:  Liegen Scores in company_data["materiality"] vor, werden diese genutzt.
  2. Auto:     Sonst werden Impact-/Financial-Scores heuristisch aus vorhandenen
               KPIs abgeleitet (sektorspezifischer Default + Signal-Boni).

Konfiguration: config/materiality_topics.yaml (NFA-3.2 / H3a).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from agents.base import BaseAgent
from utils.config_loader import get_by_path, load_yaml

_CONFIG_PATH = "config/materiality_topics.yaml"


@dataclass
class ThemenWesentlichkeit:
    """Wesentlichkeitsbewertung eines einzelnen ESRS-Themas."""
    id: str
    name_de: str
    standard: str
    impact_score: float       # Inside-Out (Auswirkung auf Umwelt/Gesellschaft)
    financial_score: float    # Outside-In (finanzielle Auswirkung auf Unternehmen)
    wesentlich: bool
    dimension: str            # "beide" | "impact" | "financial" | "keine"
    quelle: str               # "manuell" | "sub-kriterien (IG 1)" | "auto-heuristik" | "sektor-default"
    begruendung: str
    impact_sub_kriterien: dict = field(default_factory=dict)  # IG 1 AR 20: Scale/Scope/Irrem/Likelihood
    sub_topic_bewertungen: list[dict] = field(default_factory=list)  # IG 1 Appendix A zweite Ebene

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MaterialitaetsErgebnis:
    """Gesamtergebnis der doppelten Wesentlichkeitsanalyse."""
    methode: str
    schwellenwert: float
    wesentliche_themen: list[str] = field(default_factory=list)
    themen: list[ThemenWesentlichkeit] = field(default_factory=list)
    zusammenfassung: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(v: float, lo: float = 1.0, hi: float = 5.0) -> float:
    return round(max(lo, min(hi, v)), 1)


class MaterialityAgent(BaseAgent):
    """Schicht-4-Agent: doppelte Wesentlichkeitsanalyse (IRO-1)."""

    name = "MaterialityAgent"

    def __init__(self, audit, config_path: str = _CONFIG_PATH) -> None:
        super().__init__(audit)
        cfg = load_yaml(config_path)
        self.topics = cfg.get("topics", [])
        self.meta = cfg.get("metadata", {})
        self.threshold = float(self.meta.get("materiality_threshold", 3.0))

    def run(self, company_data: dict) -> MaterialitaetsErgebnis:
        self._log("materiality_started")

        manuelle = company_data.get("materiality", {})
        nutze_manuell = bool(manuelle)
        methode = "manuell" if nutze_manuell else "auto-heuristik (datenbasiert)"

        ergebnisse: list[ThemenWesentlichkeit] = []
        for topic in self.topics:
            tid = topic["id"]
            if nutze_manuell and tid in manuelle:
                impact = float(manuelle[tid].get("impact", topic["sector_default_impact"]))
                financial = float(manuelle[tid].get("financial", topic["sector_default_financial"]))
                quelle = "manuell"
                sub_kriterien: dict = {}
            else:
                impact, financial, quelle, sub_kriterien = self._auto_score(topic, company_data)

            impact, financial = _clamp(impact), _clamp(financial)
            imp_wesentlich = impact >= self.threshold
            fin_wesentlich = financial >= self.threshold
            wesentlich = imp_wesentlich or fin_wesentlich

            if imp_wesentlich and fin_wesentlich:
                dimension = "beide"
            elif imp_wesentlich:
                dimension = "impact"
            elif fin_wesentlich:
                dimension = "financial"
            else:
                dimension = "keine"

            sub_topic_bewertungen = self._bewerte_sub_topics(topic, company_data)

            ergebnisse.append(ThemenWesentlichkeit(
                id=tid, name_de=topic["name_de"], standard=topic["standard"],
                impact_score=impact, financial_score=financial,
                wesentlich=wesentlich, dimension=dimension, quelle=quelle,
                begruendung=self._begruendung(topic, impact, financial, dimension, quelle, sub_kriterien),
                impact_sub_kriterien=sub_kriterien,
                sub_topic_bewertungen=sub_topic_bewertungen,
            ))

        wesentliche = [e.standard for e in ergebnisse if e.wesentlich]
        zusammenfassung = self._zusammenfassung(ergebnisse, methode)

        self._log("materiality_completed", {
            "methode": methode,
            "wesentliche_themen": len(wesentliche),
            "themen_gesamt": len(ergebnisse),
        })

        return MaterialitaetsErgebnis(
            methode=methode,
            schwellenwert=self.threshold,
            wesentliche_themen=wesentliche,
            themen=ergebnisse,
            zusammenfassung=zusammenfassung,
        )

    # -- Auto-Bewertung aus KPIs / Sub-Kriterien --------------------------

    def _auto_score(self, topic: dict, data: dict) -> tuple[float, float, str, dict]:
        """Berechnet Impact- und Financial-Score.

        Impact:   Vorrang haben impact_criteria (IG 1 AR 20: Scale/Scope/Irrem/Likelihood).
                  Fehlen diese, wird der sector_default + KPI-Signale verwendet.
        Financial: immer sector_default + financial_signals (KPI-basiert).
        """
        # -- Impact -----------------------------------------------------------
        sub_kriterien = topic.get("impact_criteria", {})
        if sub_kriterien:
            impact = self._impact_from_criteria(sub_kriterien)
            quelle = "sub-kriterien (IG 1)"
        else:
            impact = float(topic.get("sector_default_impact", 2.0))
            impact_signal = False
            for sig in topic.get("impact_signals", []) or []:
                val = get_by_path(data, sig["path"])
                w = sig.get("weight", 1.0)
                if isinstance(val, (int, float)) and val >= sig["threshold"] and w > 0:
                    impact += w
                    impact_signal = True
            quelle = "auto-heuristik" if impact_signal else "sektor-default"

        # -- Financial --------------------------------------------------------
        financial = float(topic.get("sector_default_financial", 2.0))
        for sig in topic.get("financial_signals", []) or []:
            val = get_by_path(data, sig["path"])
            w = sig.get("weight", 1.0)
            if isinstance(val, (int, float)) and val >= sig["threshold"] and w > 0:
                financial += w

        return impact, financial, quelle, sub_kriterien

    def _impact_from_criteria(self, criteria: dict) -> float:
        """Berechnet den Impact-Score aus IG 1-Sub-Kriterien (ESRS 1 AR 20).

        Formel:
          severity = max(scale, scope, irremediability)
            -> IG 1 AR 20: 'Any of the three can make a negative impact severe'
          Fuer potential impacts: severity angepasst um Likelihood-Faktor
            score = severity + (likelihood - 3) * 0.3
          Fuer actual impacts: Likelihood nicht bewertet (IG 1 para 44a)
            score = severity
        """
        scale = float(criteria.get("scale", 3.0))
        scope = float(criteria.get("scope", 3.0))
        irrem = float(criteria.get("irremediability", 3.0))
        typ = criteria.get("type", "potential")

        severity = max(scale, scope, irrem)

        if typ == "potential":
            likelihood = float(criteria.get("likelihood", 3.0))
            score = severity + (likelihood - 3.0) * 0.3
        else:
            score = severity  # actual: keine Likelihood-Anpassung (IG 1 para 44a)

        return score

    def _begruendung(self, topic: dict, impact: float, financial: float,
                     dimension: str, quelle: str, sub_k: dict | None = None) -> str:
        dim_text = {
            "beide": "in beiden Dimensionen (Impact und Financial) wesentlich",
            "impact": "impact-wesentlich (Auswirkung auf Umwelt/Gesellschaft)",
            "financial": "finanziell wesentlich (Auswirkung auf das Unternehmen)",
            "keine": "nicht wesentlich",
        }[dimension]

        if sub_k:
            typ = sub_k.get("type", "potential")
            scale = sub_k.get("scale", "-")
            scope = sub_k.get("scope", "-")
            irrem = sub_k.get("irremediability", "-")
            lik = sub_k.get("likelihood")
            lik_text = f", Likelihood={lik}" if lik is not None else " (actual – keine Likelihood-Bewertung)"
            kriterien_text = (
                f"IG 1-Kriterien: Scale={scale}, Scope={scope}, "
                f"Irremediabilitaet={irrem}{lik_text} [Typ: {typ}]; "
                f"severity=max({scale},{scope},{irrem})={max(float(scale), float(scope), float(irrem))}"
            )
            return (
                f"{topic['name_de']} ({topic['standard']}) ist {dim_text} "
                f"[Impact={impact}, Financial={financial}, Schwelle {self.threshold}]. "
                f"{kriterien_text}. Financial-Score aus Sektorbenchmark + KPI-Signalen."
            )

        quelle_text = {
            "manuell": "auf Basis manueller Wesentlichkeitsbewertung",
            "auto-heuristik": "abgeleitet aus vorhandenen KPI-Signalen",
            "sektor-default": "auf Basis sektorspezifischer Default-Relevanz (Finanzdienstleister)",
        }.get(quelle, quelle)
        return (
            f"{topic['name_de']} ({topic['standard']}) ist {dim_text} "
            f"[Impact-Score {impact}, Financial-Score {financial}, Schwelle {self.threshold}], "
            f"{quelle_text}."
        )

    def _bewerte_sub_topics(self, topic: dict, data: dict) -> list[dict]:
        """Bewertet Sub-Topics (IG 1 Appendix A, zweite Ebene) wenn vorhanden.

        Sub-Topics mit impact_criteria erhalten eine vollstaendige Bewertung.
        Sub-Topics mit status='pending' werden als 'ausstehend' markiert.
        """
        sub_topics = topic.get("sub_topics", [])
        if not sub_topics:
            return []

        ergebnisse = []
        for st in sub_topics:
            if st.get("status") == "pending":
                ergebnisse.append({
                    "id": st["id"],
                    "name_de": st["name_de"],
                    "appendix_a_ref": st.get("appendix_a_ref", ""),
                    "impact_score": None,
                    "financial_score": None,
                    "wesentlich": None,
                    "status": "ausstehend",
                })
                continue

            # Vollstaendige Bewertung wenn Kriterien vorhanden
            ic = st.get("impact_criteria", {})
            impact = _clamp(self._impact_from_criteria(ic)) if ic else float(
                st.get("sector_default_impact", 2.0))

            financial = float(st.get("sector_default_financial", 2.0))
            for sig in st.get("financial_signals", []) or []:
                val = get_by_path(data, sig["path"])
                w = sig.get("weight", 1.0)
                if isinstance(val, (int, float)) and val >= sig["threshold"] and w > 0:
                    financial += w
            financial = _clamp(financial)

            wesentlich = impact >= self.threshold or financial >= self.threshold
            ergebnisse.append({
                "id": st["id"],
                "name_de": st["name_de"],
                "appendix_a_ref": st.get("appendix_a_ref", ""),
                "impact_score": impact,
                "financial_score": financial,
                "wesentlich": wesentlich,
                "status": "bewertet",
            })

        return ergebnisse

    def _zusammenfassung(self, ergebnisse, methode: str) -> str:
        wesentlich = [e for e in ergebnisse if e.wesentlich]
        beide = [e for e in wesentlich if e.dimension == "beide"]
        namen = ", ".join(f"{e.name_de} ({e.standard})" for e in wesentlich)
        beide_namen = ", ".join(f"{e.standard}" for e in beide)
        return (
            f"Die doppelte Wesentlichkeitsanalyse (Methode: {methode}) identifiziert "
            f"{len(wesentlich)} von {len(ergebnisse)} ESRS-Themen als wesentlich: {namen or 'keine'}. "
            f"In beiden Dimensionen (Impact und Financial) wesentlich: {beide_namen or 'keine'}. "
            f"Fuer Finanzinstitute ist E1 (Klimawandel) regelmaessig der wesentlichste Umweltstandard, "
            f"da finanzierte Emissionen (Scope 3 Kat. 15) sowohl hohe Klimaauswirkung (Impact) als auch "
            f"transitorische und physische Risiken (Financial) verursachen. Die Analyse begruendet die "
            f"Fokussierung der Berichterstattung auf die als wesentlich identifizierten Standards "
            f"(ESRS 1, Kapitel 3)."
        )
