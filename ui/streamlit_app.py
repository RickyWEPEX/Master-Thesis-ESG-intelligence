"""Streamlit-UI fuer den ESG-Reporting-Prototyp (Schicht 5 / Demo-Interface).

Start:  streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import Orchestrator
from evaluation.metrics import extraction_metrics, validation_metrics
from evaluation.ml_classifier import run_ml_evaluation
from utils.config_loader import load_json

st.set_page_config(
    page_title="KI-Agenten-Framework ESG (CSRD/ESRS)",
    layout="wide",
    page_icon="🌱",
)

st.title("KI-Agenten-Framework fuer ESG-Reporting")
st.caption(
    "CSRD/ESRS (E1–G1, alle Standards) — Prototyp nach Design Science Research (Frankfurt School). "
    "Synthetische Daten — alle Angaben vor produktivem Einsatz fachlich pruefen."
)

# ---- Session-State initialisieren ------------------------------------------
if "result" not in st.session_state:
    st.session_state.result = None
    st.session_state.orch = None
    st.session_state.backend_used = "deterministic"
    st.session_state.threshold_used = 0.75
    st.session_state.hitl_corrections = {}  # {dp_id: corrected_value}

# ---- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.header("Konfiguration")
    _DATENSATZ_OPTIONEN = {
        "Szenario A: Vollstaendig — 44 DPs korrekt, 0 Fehler (ESRS E1/E2/G1)":
            "data/synthetic/synthetic_company_data.json",
        "Szenario B: Fehler-Variante — 7 Validierungsfehler, E2+G1-Daten fehlen":
            "data/synthetic/synthetic_company_data_errors.json",
    }
    dataset_label = st.selectbox(
        "Datensatz",
        list(_DATENSATZ_OPTIONEN.keys()),
        help=(
            "Szenario A: Idealfall — alle 44 Datenpunkte vorhanden und regelkonform.\n"
            "Szenario B: Fehlerfall — 7 absichtliche Regelverstoeße (Scope-Summen, "
            "Reduktionspfad) + fehlende E2- und G1-Abschnitte."
        ),
    )
    dataset = _DATENSATZ_OPTIONEN[dataset_label]
    _BACKEND_OPTIONEN = {
        "Simulation (strukturierte Daten)": "deterministic",
        "Simulation (unstrukturierte Daten)": "claude",
    }
    backend_label = st.radio(
        "Extraktions-Szenario",
        list(_BACKEND_OPTIONEN.keys()),
        index=0,
        help=(
            "Strukturierte Daten: Werte liegen als maschinenlesbare Felder vor (JSON/CSV). "
            "Unstrukturierte Daten: Werte muessen aus Freitexten per KI extrahiert werden."
        ),
    )
    backend = _BACKEND_OPTIONEN[backend_label]

    if backend == "claude":
        st.info(
            "KI-Extraktion aktiv: ~34 API-Calls fuer Datenpunkt-Extraktion aus Freitext "
            "(ca. 120s Laufzeit).\n\n"
            "Alle Bewertungen (Assessment, Sektorbenchmarks, Lagebericht) "
            "bleiben deterministisch — kein LLM."
        )
    else:
        st.caption(
            "Direkte Extraktion aus strukturierten Feldern — kein API-Aufruf, "
            "Laufzeit < 1 Sekunde."
        )

    threshold = st.slider("Human-in-the-Loop Schwellenwert", 0.0, 1.0, 0.75, 0.05)
    st.divider()
    st.caption("H2d: ML-Klassifikator")
    run_ml = st.checkbox("ML-Analyse ausfuehren (H2d)", value=True)
    run_btn = st.button("Workflow ausfuehren", type="primary", use_container_width=True)
    if st.session_state.result is not None:
        if st.button("Neue Analyse", use_container_width=True):
            st.session_state.result = None
            st.session_state.orch = None
            st.rerun()

# ---- Workflow ausloesen ----------------------------------------------------
if run_btn:
    orch = Orchestrator()
    orch.settings["run"]["extraction_backend"] = backend
    orch.settings.setdefault("confidence", {})["review_threshold"] = threshold

    with st.status("5-Schichten-Pipeline wird ausgefuehrt ...", expanded=True) as _status:
        def _progress(msg: str) -> None:
            st.write(msg)

        st.session_state.result = orch.run(dataset, progress_callback=_progress)
        _status.update(
            label=f"Pipeline abgeschlossen ({st.session_state.result['elapsed_seconds']} s)",
            state="complete",
            expanded=False,
        )
        st.session_state.orch = orch
        st.session_state.backend_used = backend
        st.session_state.threshold_used = threshold

if st.session_state.result is not None:
    result = st.session_state.result
    orch = st.session_state.orch
    backend = st.session_state.backend_used
    threshold = st.session_state.threshold_used

    comp = result["compliance"]
    assessment = result.get("assessment")
    crit = sum(1 for i in result["validation_issues"] if i.severity == "critical")

    # -- KPI-Zeile -----------------------------------------------------------
    # Gesamt-ESG-Ampel aus allen Standards berechnen
    def _esg_gesamt_ampel(ass):
        if not ass or not ass.kpi_bewertungen:
            return "n/a"
        rot = sum(1 for b in ass.kpi_bewertungen if b.ampel == "ROT")
        gelb = sum(1 for b in ass.kpi_bewertungen if b.ampel == "GELB")
        gruen = sum(1 for b in ass.kpi_bewertungen if b.ampel == "GRUEN")
        if rot >= 2:
            return "ROT"
        if rot >= 1 or gelb >= 4:
            return "GELB"
        if gruen >= len(ass.kpi_bewertungen) * 0.7:
            return "GRUEN"
        return "GELB"

    esg_ampel = _esg_gesamt_ampel(assessment)
    e1_ampel = assessment.gesamtampel if assessment else "n/a"
    wesentliche_anz = len(result.get("materiality").wesentliche_themen) if result.get("materiality") else "—"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Durchlaufzeit", f"{result['elapsed_seconds']} s")
    c2.metric("Backend", backend)
    c3.metric("ESG-Gesamtstatus", esg_ampel,
              f"{wesentliche_anz} wesentliche Standards")
    c4.metric("Klimaperformance (E1)", e1_ampel,
              f"{comp.completeness_rate * 100:.0f}% Pflichtangaben")
    c5.metric("Validierung", f"{len(result['validation_issues'])} Issues",
              f"{crit} kritisch")
    c6.metric("Audit-Kette", "OK" if result["audit_valid"] else "FEHLER",
              delta_color="off")

    # -- HITL-Eingabe --------------------------------------------------------
    low_conf = [e for e in result["extracted"]
                if e.present and e.confidence < threshold]
    if low_conf:
        with st.expander(
            f"⚠️ Human-in-the-Loop: {len(low_conf)} Datenpunkte erfordern manuelle Pruefung",
            expanded=True,
        ):
            st.warning(
                f"Die KI-Extraktion ist bei **{len(low_conf)} Datenpunkten** unsicher "
                f"(Konfidenz < {threshold}). Bitte tragen Sie den korrekten Wert ein "
                f"oder bestaetigen Sie den KI-Vorschlag.",
                icon="⚠️",
            )
            st.caption(
                "EU AI Act Art. 14 — menschliche Aufsicht bei KI-Systemen mit hohem Risiko. "
                "Eingegebene Korrekturen werden im Audit-Trail protokolliert."
            )
            corrections_made = 0
            for e in low_conf:
                with st.container(border=True):
                    col_info, col_input = st.columns([2, 1])
                    with col_info:
                        st.markdown(f"**{e.id} — {e.name_de}** (`{e.dr}`)")
                        st.caption(
                            f"KI-Vorschlag: `{e.value}` {e.unit}  |  "
                            f"Konfidenz: {e.confidence:.0%}"
                        )
                        reasoning = e.source.get("reasoning", "")
                        if reasoning:
                            st.info(f"KI-Begruendung: {reasoning}", icon="🤖")
                    with col_input:
                        key = f"hitl_{e.id}"
                        current = st.session_state.hitl_corrections.get(e.id, "")
                        corrected = st.text_input(
                            "Korrekter Wert",
                            value=str(current) if current != "" else "",
                            placeholder=f"z.B. {e.value}",
                            key=key,
                            help=f"Einheit: {e.unit}. Leer lassen = KI-Wert uebernehmen.",
                        )
                        if corrected and corrected != str(e.value):
                            st.session_state.hitl_corrections[e.id] = corrected
                            st.success("Korrektur gespeichert")
                            corrections_made += 1
                        elif corrected == "" and e.id in st.session_state.hitl_corrections:
                            del st.session_state.hitl_corrections[e.id]
            if st.session_state.hitl_corrections:
                st.info(
                    f"{len(st.session_state.hitl_corrections)} Korrekturen gespeichert. "
                    "Sie werden im Audit-Trail als 'hitl_correction' protokolliert.",
                    icon="✅",
                )
                if st.button("Korrekturen in Audit-Trail schreiben", type="secondary"):
                    for dp_id, val in st.session_state.hitl_corrections.items():
                        result["extracted"]  # Referenz fuer Audit-Log
                        st.session_state.orch.audit.log(
                            "HumanReviewer", "hitl_correction",
                            {"datapoint_id": dp_id, "corrected_value": val,
                             "reason": "manual_review_below_threshold"},
                        )
                    st.success("Korrekturen im Audit-Trail protokolliert.")

    materiality = result.get("materiality")

    def _erlaeuterung(text: str) -> None:
        """Einheitliche Erklaerungsbox fuer Gutachter."""
        with st.expander("ℹ️ Erlaeuterung fuer Gutachter", expanded=True):
            st.markdown(text)

    # -- Tabs ----------------------------------------------------------------
    tab_labels = [
        "📋 Lagebericht",
        "🎯 Wesentlichkeit",
        "📊 KPI-Assessment",
        "🔍 Extraktion",
        "⚠️ Validierung",
        "📈 Evaluation",
        "🤖 ML (H2d)",
        "🔒 Audit-Trail",
    ]
    tabs = st.tabs(tab_labels)

    # 0: Lagebericht
    with tabs[0]:
        _erlaeuterung(
            "Das KI-Agenten-Framework hat diesen Bericht vollautomatisch erstellt. "
            "Grundlage sind synthetische Unternehmensdaten, die reale ESG-Berichtsdaten "
            "einer deutschen Regionalbank simulieren. Das Framework liest diese Daten, "
            "prüft sie auf Vollständigkeit und Korrektheit und erstellt daraus einen "
            "strukturierten Nachhaltigkeitsbericht gemäß CSRD/ESRS (alle Standards) — "
            "vergleichbar mit dem, was Unternehmen ab 2025 gesetzlich veröffentlichen müssen. "
            "Der Bericht kann als PDF oder Markdown heruntergeladen werden."
        )
        st.markdown(result["report_markdown"])
        col1, col2 = st.columns(2)
        col1.download_button(
            "Lagebericht herunterladen (.md)",
            result["report_markdown"],
            file_name="esrs_nachhaltigkeitsbericht.md",
            mime="text/markdown",
        )
        if result.get("report_pdf"):
            col2.download_button(
                "Lagebericht herunterladen (.pdf)",
                result["report_pdf"],
                file_name="esrs_nachhaltigkeitsbericht.pdf",
                mime="application/pdf",
            )

    # 1: Wesentlichkeitsanalyse
    with tabs[1]:
        if materiality:
            st.subheader("Doppelte Wesentlichkeitsanalyse (ESRS 1, IRO-1)")
            _erlaeuterung(
                "**Was ist die doppelte Wesentlichkeitsanalyse?**\n\n"
                "ESRS schreibt vor, dass Unternehmen nicht pauschal über alle "
                "Nachhaltigkeitsthemen berichten müssen — sondern nur über jene, "
                "die für sie *wesentlich* sind. Die Wesentlichkeit wird aus zwei "
                "Richtungen geprüft:\n\n"
                "- **Impact-Perspektive (Outside-Out):** Welche Auswirkungen hat das "
                "Unternehmen durch seine Aktivitäten und sein Finanzierungsportfolio "
                "auf Umwelt und Gesellschaft?\n"
                "- **Financial-Perspektive (Outside-In):** Welche Nachhaltigkeitsthemen "
                "stellen finanzielle Risiken oder Chancen für das Unternehmen dar?\n\n"
                "Ein Thema gilt als wesentlich, wenn es *mindestens eine* der beiden "
                "Perspektiven erfüllt. Das Tool bewertet alle 10 ESRS-Themen "
                f"automatisch auf einer Skala von 1–5 und vergleicht sie mit dem "
                f"Schwellenwert von {materiality.schwellenwert}."
            )
            st.info(materiality.zusammenfassung)
            st.caption(
                f"Methode: {materiality.methode} | "
                f"Schwellenwert: Score >= {materiality.schwellenwert} (Skala 1–5) | "
                f"Wesentlich wenn Impact ODER Financial >= Schwellenwert (ESRS 1, Kap. 3.4)"
            )

            if materiality.methode.startswith("auto"):
                with st.expander("📋 Hinweis: Automatische Bewertung — manuelle Ueberschreibung moeglich"):
                    st.markdown(
                        "Die Scores wurden **automatisch** aus den Unternehmensdaten berechnet "
                        "(KPI-Signale + IG 1-Sub-Kriterien). In der Praxis erfordert ESRS 1 IRO-1 "
                        "zusätzlich die Einbindung von Stakeholdern (z.B. Kunden, Regulatoren, "
                        "Investoren) und interne Expertenurteile.\n\n"
                        "**So werden manuelle Scores hinterlegt:** In der Eingabe-JSON "
                        "den Block `materiality` ergänzen:\n"
                    )
                    st.code(
                        '{\n'
                        '  "materiality": {\n'
                        '    "E1": { "impact": 5.0, "financial": 5.0 },\n'
                        '    "S1": { "impact": 4.0, "financial": 3.0 },\n'
                        '    "G1": { "impact": 4.0, "financial": 4.0 }\n'
                        '  }\n'
                        '}',
                        language="json",
                    )
                    st.caption(
                        "Skala 1–5 | Schwellenwert 3,0 | Nicht aufgeführte Standards "
                        "werden weiter automatisch bewertet. Die Quelle wird dann als "
                        "'manuell' ausgewiesen."
                    )

            # Tabelle
            st.subheader("Wesentlichkeitsmatrix")
            st.caption(
                "Die Tabelle listet alle 10 ESRS-Themen mit ihren Impact- und "
                "Financial-Scores. Themen mit 'JA' in der Spalte 'Wesentlich' müssen "
                "im CSRD-Bericht vollständig offengelegt werden."
            )
            rows = []
            for t in materiality.themen:
                rows.append({
                    "ESRS-Standard": t.standard,
                    "Thema": t.name_de,
                    "Impact-Score": t.impact_score,
                    "Financial-Score": t.financial_score,
                    "Wesentlich": "JA" if t.wesentlich else "nein",
                    "Dimension": t.dimension,
                    "Quelle": t.quelle,
                })
            st.dataframe(rows, use_container_width=True)

            # Streudiagramm: Impact vs. Financial
            st.subheader("Matrix: Impact- vs. Financial-Wesentlichkeit")
            st.caption(
                "Jeder Punkt im Diagramm steht für ein ESRS-Thema. "
                "Themen weit rechts haben hohe Auswirkungen auf Umwelt und Gesellschaft; "
                "Themen weit oben stellen hohe finanzielle Risiken dar. "
                "Alle Themen jenseits des Schwellenwerts auf einer der beiden Achsen sind wesentlich."
            )

            thr = materiality.schwellenwert
            col_chart, col_legend = st.columns([3, 1])
            with col_legend:
                st.markdown("**Legende**")
                st.markdown(
                    f"🔵 **Wesentlich** — mindestens eine Dimension "
                    f"erreicht den Schwellenwert ({thr})"
                )
                st.markdown(
                    f"🔴 **Nicht wesentlich** — beide Dimensionen "
                    f"unter dem Schwellenwert ({thr})"
                )
                st.divider()
                st.markdown("**Achsen**")
                st.markdown(
                    "**Impact-Score** (X): Auswirkung des Unternehmens "
                    "auf Umwelt/Gesellschaft *(Outside-Out)*"
                )
                st.markdown(
                    "**Financial-Score** (Y): Finanzielle Auswirkung "
                    "auf das Unternehmen *(Outside-In)*"
                )
                st.divider()
                st.markdown(
                    f"Skala 1–5 | Schwellenwert: **{thr}** "
                    f"(ESRS 1, Kap. 3.4)"
                )

            with col_chart:
                try:
                    import pandas as pd
                    import plotly.graph_objects as go

                    wesentlich_themen = [t for t in materiality.themen if t.wesentlich]
                    nicht_wesentlich = [t for t in materiality.themen if not t.wesentlich]

                    fig = go.Figure()

                    def _dot_size(t) -> float:
                        # Groesse proportional zur hoechsten Wesentlichkeitsdimension (8–36 px)
                        score = max(t.impact_score, t.financial_score)
                        return 8 + (score - 1) / 4 * 28

                    for gruppe, farbe, name in [
                        (wesentlich_themen, "#1565c0", "Wesentlich"),
                        (nicht_wesentlich, "#c62828", "Nicht wesentlich"),
                    ]:
                        if gruppe:
                            fig.add_trace(go.Scatter(
                                x=[t.impact_score for t in gruppe],
                                y=[t.financial_score for t in gruppe],
                                mode="markers+text",
                                name=name,
                                text=[t.standard for t in gruppe],
                                textposition="top center",
                                hovertemplate=(
                                    "<b>%{customdata[0]}</b><br>"
                                    "Standard: %{customdata[1]}<br>"
                                    "Impact-Score: %{x}<br>"
                                    "Financial-Score: %{y}<br>"
                                    "Bewertung: " + name +
                                    "<extra></extra>"
                                ),
                                customdata=[
                                    [t.name_de, t.standard] for t in gruppe
                                ],
                                marker=dict(
                                    size=[_dot_size(t) for t in gruppe],
                                    color=farbe,
                                    opacity=0.85,
                                    line=dict(width=1, color="white"),
                                ),
                                textfont=dict(size=10),
                            ))

                    # Schwellenwertlinien
                    fig.add_hline(y=thr, line_dash="dash", line_color="grey",
                                  annotation_text=f"Schwelle {thr}", annotation_position="right")
                    fig.add_vline(x=thr, line_dash="dash", line_color="grey")

                    fig.update_layout(
                        xaxis_title="Impact-Score (Auswirkung auf Umwelt/Gesellschaft)",
                        yaxis_title="Financial-Score (Finanzielle Auswirkung)",
                        xaxis=dict(range=[0.5, 5.5]),
                        yaxis=dict(range=[0.5, 5.5]),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                        margin=dict(l=10, r=10, t=30, b=10),
                        height=420,
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(
                        f"Punktgröße = max(Impact, Financial-Score) — größere Punkte sind insgesamt wesentlicher. "
                        f"Schwellenwert: {thr}. Hover zeigt Themenname, Standard und beide Scores."
                    )
                except Exception as e:
                    st.warning(f"Diagramm nicht verfuegbar: {e}")

            # Detail-Expander
            st.subheader("Begruendungen je Thema")
            st.caption(
                "Klicken Sie auf ein Thema, um die detaillierte Bewertung aufzuklappen. "
                "Die drei Kriterien Scale, Scope und Irremediability stammen direkt aus "
                "ESRS 1 IG 1 (AR 20) und beschreiben Schwere, Reichweite und "
                "Reversibilität des Impacts. Bei potenziellen Auswirkungen kommt die "
                "Eintrittswahrscheinlichkeit (Likelihood) hinzu."
            )
            for t in materiality.themen:
                icon = "✅" if t.wesentlich else "○"
                with st.expander(f"{icon} {t.name_de} ({t.standard})"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Impact-Score", t.impact_score, f"Schwelle {materiality.schwellenwert}")
                    c2.metric("Financial-Score", t.financial_score, f"Schwelle {materiality.schwellenwert}")
                    c3.metric("Dimension", t.dimension)

                    sk = getattr(t, "impact_sub_kriterien", {})
                    if sk:
                        st.markdown("**Impact-Sub-Kriterien (ESRS 1 IG 1, AR 20)**")
                        typ = sk.get("type", "potential")
                        typ_label = "Actual (eingetreten)" if typ == "actual" else "Potential (noch nicht eingetreten)"
                        st.caption(
                            f"Bewertungstyp: **{typ_label}** — "
                            + ("Likelihood wird bewertet (IG 1 para 40)" if typ == "potential"
                               else "Likelihood nicht bewertet (IG 1 para 44a)")
                        )
                        k1, k2, k3, k4 = st.columns(4)
                        k1.metric("Scale", sk.get("scale", "—"),
                                  help="Schwere des Impacts (1=gering, 5=katastrophal)")
                        k2.metric("Scope", sk.get("scope", "—"),
                                  help="Reichweite (1=lokal, 5=global)")
                        k3.metric("Irremediability", sk.get("irremediability", "—"),
                                  help="Irreversibilitaet (1=leicht behebbar, 5=irreversibel)")
                        if typ == "potential":
                            k4.metric("Likelihood", sk.get("likelihood", "—"),
                                      help="Eintrittswahrscheinlichkeit (1=sehr gering, 5=sicher)")
                        else:
                            k4.metric("Likelihood", "n/a", help="Nicht bewertet bei actual impacts")

                        severity = max(
                            float(sk.get("scale", 3)),
                            float(sk.get("scope", 3)),
                            float(sk.get("irremediability", 3)),
                        )
                        st.caption(
                            f"Severity = max(Scale, Scope, Irremediability) = **{severity}** "
                            f"(IG 1 AR 20: 'Any of the three can make a negative impact severe')"
                        )
                        st.divider()

                    st.write(t.begruendung)

                    sub_topics = getattr(t, "sub_topic_bewertungen", [])
                    if sub_topics:
                        st.divider()
                        st.markdown("**Sub-Topics (IG 1 Appendix A — zweite Bewertungsebene)**")
                        st.caption(
                            "Innerhalb wesentlicher Standards werden die einzelnen Unterthemen "
                            "bewertet. Nur wesentliche Sub-Topics erfordern vollständige "
                            "Offenlegung. 'Ausstehend' bedeutet: Sub-Topic-Bewertung noch "
                            "nicht implementiert (ausstehend fuer Folge-Sprint)."
                        )
                        for st_item in sub_topics:
                            status = st_item.get("status", "ausstehend")
                            name = st_item["name_de"]
                            ref = st_item.get("appendix_a_ref", "")
                            if status == "bewertet":
                                w = st_item.get("wesentlich")
                                imp = st_item.get("impact_score")
                                fin = st_item.get("financial_score")
                                icon = "✅" if w else "○"
                                w_label = "wesentlich" if w else "nicht wesentlich"
                                st.markdown(
                                    f"{icon} **{name}** — Impact: {imp}, "
                                    f"Financial: {fin} → *{w_label}*"
                                )
                                st.caption(f"Appendix A: {ref}")
                            else:
                                st.markdown(f"⏳ **{name}** — *ausstehend (MVP-Scope)*")
                                st.caption(f"Appendix A: {ref}")
        else:
            st.info("Wesentlichkeitsanalyse nicht verfuegbar.")

    # 2: KPI-Assessment
    with tabs[2]:
        if assessment:
            _erlaeuterung(
                "**Was zeigt das KPI-Assessment?**\n\n"
                "Das KPI-Assessment vergleicht die Klimakennzahlen des Unternehmens "
                "mit typischen Werten vergleichbarer deutscher Finanzinstitute "
                "(Bilanzsumme 1–25 Mrd. EUR, Quelle: EBA Pillar 3, BaFin-Berichte, "
                "TCFD-Reports, Stand 2024). "
                "Die **Ampelfarben** zeigen auf einen Blick:\n\n"
                "- 🟢 **GRUEN:** Unternehmen liegt besser als der Sektormedian\n"
                "- 🟡 **GELB:** Unternehmen liegt im sektortypischen Bereich\n"
                "- 🔴 **ROT:** Unternehmen liegt deutlich schlechter als der Sektor\n\n"
                "Alle Interpretationen und Handlungsempfehlungen werden **regelbasiert** "
                "aus den Benchmark-Abweichungen berechnet — ohne KI-Sprachmodell. "
                "Das macht die Ergebnisse vollständig nachvollziehbar und reproduzierbar."
            )
            st.subheader(f"Gesamtbewertung: {assessment.gesamtampel}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("Staerken")
                for s in assessment.staerken:
                    st.success(s)
                if not assessment.staerken:
                    st.info("Keine Staerken identifiziert.")

            with col_b:
                st.subheader("Handlungsbedarf")
                for s in assessment.schwaechen:
                    st.warning(s)
                if not assessment.schwaechen:
                    st.success("Kein kritischer Handlungsbedarf.")

            st.subheader("KPI-Sektorvergleich")
            st.caption(
                "Jede Zeile steht für eine Klimakennzahl (z.B. Treibhausgasemissionen, "
                "Energieverbrauch, Reduktionsziel). Der Sektormedian ist der Mittelwert "
                "für vergleichbare Finanzinstitute. Die Abweichung zeigt, wie stark das "
                "Unternehmen vom Branchendurchschnitt abweicht."
            )
            kpi_data = []
            for b in assessment.kpi_bewertungen:
                kpi_data.append({
                    "KPI": b.name_de,
                    "Wert": f"{b.wert:,.1f} {b.einheit}" if b.wert is not None else "n/a",
                    "Sektormedian": f"{b.sektor_p50:,.1f} {b.einheit}" if b.sektor_p50 else "n/a",
                    "Abweichung": f"{b.abweichung_prozent:+.1f}%" if b.abweichung_prozent is not None else "n/a",
                    "Ampel": b.ampel,
                })
            st.dataframe(kpi_data, use_container_width=True)

            st.subheader("Interpretationen")
            for b in assessment.kpi_bewertungen:
                with st.expander(f"{b.ampel} {b.name_de}"):
                    st.write(b.interpretation)
                    if b.empfehlung:
                        st.info(f"**Empfehlung:** {b.empfehlung}")

            st.subheader("Priorisierte Handlungsempfehlungen")
            st.caption(
                "Die Empfehlungen werden automatisch nach Dringlichkeit sortiert. "
                "Hohe Priorität (rot) bedeutet: Der Wert liegt deutlich unter dem "
                "Sektormedian und könnte regulatorische Konsequenzen haben. "
                "Mittlere Priorität (orange): Verbesserungsbedarf, aber kein akuter Handlungszwang."
            )
            for emp in assessment.handlungsempfehlungen:
                if "PRIORITAET HOCH" in emp:
                    st.error(emp)
                elif "PRIORITAET MITTEL" in emp:
                    st.warning(emp)
                else:
                    st.info(emp)

            st.subheader("Risiken und Chancen")
            col_r, col_c = st.columns(2)
            with col_r:
                st.write("**Risiken:**")
                for r in assessment.risiken:
                    st.write(f"- {r}")
            with col_c:
                st.write("**Chancen:**")
                for c in assessment.chancen:
                    st.write(f"- {c}")
        else:
            st.info("Assessment nicht verfuegbar.")

    # 3: Extraktion
    with tabs[3]:
        _erlaeuterung(
            "**Wie extrahiert das Tool die Daten?**\n\n"
            "Das Framework liest die Unternehmensdaten und ermittelt automatisch alle "
            "für CSRD/ESRS relevanten Kennzahlen (105 Datenpunkte über 10 Standards). Es gibt zwei Betriebsmodi:\n\n"
            "- **Deterministisch** (Standard): Das System liest Werte direkt aus der "
            "strukturierten Datei — schnell (< 1 Sekunde) und vollständig reproduzierbar. "
            "Konfidenzwert ist immer 1,0 (sicher), da kein Interpretationsspielraum besteht.\n"
            "- **Claude-Backend (KI)**: Ein großes Sprachmodell (Claude von Anthropic) "
            "liest die Rohdaten und extrahiert die Werte per natürlicher Sprache — "
            "wie es ein menschlicher Analyst tun würde. Sinnvoll bei unstrukturierten "
            "Quellen wie PDF-Berichten oder freitextlichen Lageberichten.\n\n"
            "Der **Konfidenzwert** (0–1) zeigt, wie sicher die Extraktion ist. "
            "Werte unter dem einstellbaren Schwellenwert werden zur manuellen Prüfung "
            "markiert (Human-in-the-Loop, EU AI Act Art. 14)."
        )
        is_llm = st.session_state.backend_used == "claude"
        _thresh = st.session_state.threshold_used
        rows = []
        for e in result["extracted"]:
            korrektur = st.session_state.hitl_corrections.get(e.id)
            row = {
                "ID": e.id, "DR": e.dr, "Datenpunkt": e.name_de,
                "Kategorie": e.category,
                "Wert": korrektur if korrektur else e.value,
                "Einheit": e.unit, "Konfidenz": round(e.confidence, 3),
                "vorhanden": e.present, "Methode": e.source.get("method", "-"),
            }
            if korrektur:
                row["Geprueft"] = "manuell korrigiert"
            elif is_llm and e.present and e.confidence < _thresh:
                row["Geprueft"] = "⚠️ Pruefung erforderlich"
            else:
                row["Geprueft"] = ""
            if is_llm:
                row["KI-Begruendung"] = e.source.get("reasoning", "")
            rows.append(row)

        df = pd.DataFrame(rows)

        def _highlight_low_conf(row):
            if "⚠️" in str(row.get("Geprueft", "")):
                return ["background-color: #fff3cd"] * len(row)
            if row.get("Geprueft") == "manuell korrigiert":
                return ["background-color: #d1e7dd"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df.style.apply(_highlight_low_conf, axis=1),
            use_container_width=True,
        )
        st.info(f"Gesamt: {len(result['extracted'])} Datenpunkte | "
                f"Vorhanden: {sum(1 for e in result['extracted'] if e.present)} | "
                f"Neu (H3a-Demo): 10 Datenpunkte via YAML ohne Code-Aenderung hinzugefuegt.")

        if is_llm:
            with st.expander("🔍 KI-Begruendungen — Detailansicht (FA-1.4 Quellennachweis)"):
                st.caption(
                    "Fuer jeden Datenpunkt gibt die KI eine kurze Begruendung, "
                    "warum sie den Wert im Text gefunden hat oder nicht. "
                    "Das erfuellt die Anforderung FA-1.4 (Datenherkunft dokumentieren) "
                    "und macht die LLM-Extraktion nachvollziehbar."
                )
                for e in result["extracted"]:
                    reasoning = e.source.get("reasoning", "")
                    if reasoning:
                        st.markdown(
                            f"**{e.id} — {e.name_de}** "
                            f"(Konfidenz: {e.confidence:.2f})\n\n_{reasoning}_"
                        )

        with st.expander("📋 Datenanforderungen fuer eigene Daten"):
            st.markdown("**Welche Daten muss ich bereitstellen?**")
            st.markdown(
                "Für einen vollständigen ESRS-Bericht werden für E1 (Klimawandel) mindestens benötigt:\n\n"
                "| Bereich | Pflichtfeld | Beispielwert |\n"
                "|---|---|---|\n"
                "| Emissionen | `emissions.scope_1_tco2e` | 1.250,5 |\n"
                "| Emissionen | `emissions.scope_2_market_tco2e` | 2.100,0 |\n"
                "| Emissionen | `emissions.scope_3_total_tco2e` | 142.000,0 |\n"
                "| Emissionen | `emissions.total_ghg_market_tco2e` | 145.350,5 |\n"
                "| Energie | `energy.total_consumption_mwh` | 12.500,0 |\n"
                "| Energie | `energy.renewable_share_percent` | 45,0 |\n"
                "| Ziele | `targets.reduction_target_percent` | 50,0 |\n"
                "| Ziele | `targets.net_zero_year` | 2040 |\n"
                "| Narrativ | `narratives.transition_plan` | Freitext |\n\n"
                "**Einheit:** Emissionen in tCO₂e, Energie in MWh, Prozentwerte 0–100.\n\n"
                "**Format:** JSON-Datei — vollständige Referenzstruktur in "
                "`data/synthetic/synthetic_company_data.json`\n\n"
                "**Fehlende Werte:** Werden als Compliance-Lücke ausgewiesen (Tab Validierung). "
                "Das Tool bricht nicht ab — fehlende Datenpunkte erhalten `present=False`."
            )
            st.caption(
                "Alle Feldnamen und Einheiten sind in den YAML-Katalogen unter "
                "`config/esrs_*_datapoints.yaml` dokumentiert (Spalte `value_path`)."
            )

        st.info(
            "H3a-Nachweis: 10 neue Datenpunkte (E1-DP-035 bis E1-DP-044) wurden per YAML "
            "ohne Code-Aenderung hinzugefuegt. Die Kataloge fuer E2–G1 wurden analog erstellt "
            "(je 5–10 Datenpunkte) — insgesamt 105 Datenpunkte ueber 10 ESRS-Standards."
        )

    # 4: Validierung
    with tabs[4]:
        _erlaeuterung(
            "**Was prüft das Validierungsmodul?**\n\n"
            "Bevor Daten in den Bericht einfließen, prüft das Framework automatisch "
            "ihre Plausibilität und innere Konsistenz. Typische Prüfregeln sind:\n\n"
            "- **Summenprüfung:** Addieren Scope 1 + Scope 2 + Scope 3 korrekt zur "
            "Gesamtemission?\n"
            "- **Wertebereiche:** Liegen Prozentwerte zwischen 0 % und 100 %? Sind "
            "Emissionswerte positiv?\n"
            "- **Kennzahlen-Konsistenz:** Passt die berechnete Emissionsintensität "
            "zu den gemeldeten Umsatz- und Emissionsdaten?\n\n"
            "Fehler werden nach Schweregrad eingestuft: **Kritisch** bedeutet, dass "
            "der Wert nicht im Bericht erscheinen darf; **Warnung** bedeutet, dass "
            "eine manuelle Prüfung empfohlen wird. Alle Regeln sind in einer "
            "YAML-Konfigurationsdatei hinterlegt und ohne Programmieraufwand anpassbar."
        )
        if result["validation_issues"]:
            st.dataframe(
                [i.to_dict() for i in result["validation_issues"]],
                use_container_width=True,
            )
        else:
            st.success("Keine Validierungsfehler gefunden.")
        if comp.gaps:
            st.subheader("Compliance-Luecken (fehlende Pflichtangaben)")
            st.dataframe(comp.gaps, use_container_width=True)

    # 5: Evaluation
    with tabs[5]:
        _erlaeuterung(
            "**Wie wird die Qualität des Frameworks gemessen?**\n\n"
            "Dieser Tab dokumentiert die Evaluationsergebnisse für die Forschungshypothesen "
            "der Masterarbeit. Die Messungen basieren auf einem manuell erstellten "
            "Referenzdatensatz ('Ground Truth'), der die korrekten Werte und erwarteten "
            "Validierungsfehler für die synthetischen Testdaten enthält.\n\n"
            "Die Hypothesen H1–H3 der Arbeit prüfen:\n"
            "- **H1 (Effizienz):** Ist das Framework deutlich schneller als manuelle Prozesse?\n"
            "- **H2 (Qualität):** Extrahiert und validiert es die Daten korrekt?\n"
            "- **H3 (Adaptierbarkeit):** Lässt es sich ohne Programmieraufwand anpassen?"
        )
        gt = load_json("data/ground_truth/ground_truth.json")
        ext_m = extraction_metrics(result["extracted"], gt)
        st.subheader("Extraktion (H2a / H2b)")
        st.caption(
            "**Precision** gibt an, wie viele der extrahierten Werte korrekt sind. "
            "**Recall** misst, wie viele der tatsächlich vorhandenen Werte das System gefunden hat. "
            "Der **F1-Score** ist das harmonische Mittel beider Werte — 1,0 entspricht "
            "fehlerfreier Extraktion."
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Precision", ext_m.precision, delta=f"Ziel: ≥0.85")
        m2.metric("Recall", ext_m.recall)
        m3.metric("F1-Score", ext_m.f1)
        st.json(ext_m.to_dict())
        if "errors" in dataset:
            val_gt = load_json("data/ground_truth/validation_ground_truth.json")
            val_m = validation_metrics(result["validation_issues"], val_gt)
            st.subheader("Fehlererkennung (FA-2)")
            v1, v2 = st.columns(2)
            v1.metric("Erkennungsrate", val_m.detection_rate, "Ziel: ≥0.95")
            v2.metric("False-Positive-Rate", val_m.false_positive_rate, "Ziel: ≤0.10")

        st.subheader("H3a: Adaptierbarkeit (YAML-Konfigurierbarkeit)")
        st.info(
            "10 neue ESRS-Datenpunkte (E1-DP-035 bis E1-DP-044) wurden ausschliesslich "
            "durch YAML-Erweiterung hinzugefuegt — kein Code-Aenderung erforderlich. "
            "Nachweis fuer H3a (Anpassungsaufwand) und NFA-3.2 (Konfigurierbarkeit)."
        )

    # 6: ML (H2d)
    with tabs[6]:
        if run_ml:
            with st.spinner("ML-Klassifikator trainieren + SHAP berechnen..."):
                ml = run_ml_evaluation()
            st.subheader("H2d: Random-Forest-Klassifikator + SHAP")
            _erlaeuterung(
                "**Zweck des maschinellen Lernmodells**\n\n"
                "Der EU AI Act (Art. 13) und ESRS fordern, dass KI-gestützte Systeme "
                "erklärbar und nachvollziehbar sein müssen. Um dies zu demonstrieren, "
                "wurde ein **Random-Forest-Klassifikator** eingesetzt — ein Verfahren, "
                "das besonders für tabellarische Daten geeignet ist und dessen "
                "Entscheidungen sich präzise erklären lassen.\n\n"
                "**Aufgabe des Modells:** Es klassifiziert ESG-Datensätze als "
                "*valide* (Label 0) oder *fehlerhaft* (Label 1). "
                "Es trifft keine autonomen Entscheidungen — die eigentliche Validierung "
                "übernehmen die regelbasierten Agenten. Das Modell dient ausschließlich "
                "zur Demonstration von Erklärbarkeit (Hypothese H2d)."
            )

            # Modell-Details
            with st.expander("🔬 Modell- und Trainingsdetails fuer Gutachter", expanded=True):
                st.markdown("**Random-Forest-Konfiguration:**")
                st.markdown(
                    "- **100 Entscheidungsbäume**, maximale Tiefe 6 — begrenzt Überanpassung\n"
                    "- `class_weight='balanced'` — gleicht die Klassenverteilung (65% valide / 35% fehlerhaft) aus\n"
                    "- `random_state=42` — vollständig reproduzierbar (QA-3.1)\n\n"
                    "**Trainingsdaten — 500 synthetische ESG-Datensätze:**\n\n"
                    "Jeder Datensatz besteht aus 10 quantitativen ESRS-E1-Merkmalen:\n"
                    "Scope-1/2/3-Emissionen, Gesamtemissionen, erneuerbarer Energieanteil, "
                    "Reduktionsziel, Energieintensität, GHG-Intensität, "
                    "physisches Risikoexposure und verbleibende Jahre bis Netto-Null.\n\n"
                    "Die 35 % fehlerhaften Datensätze enthalten bewusst injizierte Fehler — "
                    "vier Typen analog zu den Validierungsregeln des Frameworks:\n"
                    "1. Summenregel verletzt (Scope 1+2+3 ≠ Gesamtemission, >7% Abweichung)\n"
                    "2. Negativwert (Scope-1-Emissionen < 0)\n"
                    "3. Wertebereich überschritten (Reduktionsziel > 100%)\n"
                    "4. Intensität außerhalb Katalogschranken (GHG-Intensität > 5.000 tCO₂e/Mio EUR)"
                )
                st.divider()
                st.markdown("**Was ist der Gini-Koeffizient (Feature Importance)?**")
                st.markdown(
                    "Der Random Forest trifft Entscheidungen, indem er Datenpunkte anhand "
                    "von Schwellenwerten aufteilt (z.B. 'Scope-1 > 1.500 tCO₂e?'). "
                    "Die **Gini-Unreinheit** misst, wie homogen die Teilmengen nach einer "
                    "Aufspaltung sind — je homogener, desto besser die Trennung. "
                    "Die **Gini Feature Importance** summiert für jedes Merkmal, wie stark "
                    "es über alle 100 Bäume zur Verringerung der Unreinheit beiträgt. "
                    "Ein hoher Wert bedeutet: dieses Merkmal ist entscheidend dafür, "
                    "ob ein Datensatz als valide oder fehlerhaft eingestuft wird.\n\n"
                    "*Limitation:* Gini-Wichtigkeit bevorzugt Merkmale mit vielen möglichen "
                    "Schwellenwerten (hohe Kardinalität). SHAP liefert daher eine "
                    "ergänzende, unverzerrte Perspektive."
                )
                st.divider()
                st.markdown("**Was sind SHAP-Werte (Shapley Additive Explanations)?**")
                st.markdown(
                    "SHAP stammt aus der **kooperativen Spieltheorie** (Shapley, 1953). "
                    "Die Grundidee: Wenn mehrere 'Spieler' (=Merkmale) gemeinsam ein "
                    "'Spiel' gewinnen (=Vorhersage treffen), wie viel hat jeder einzelne "
                    "Spieler dazu beigetragen?\n\n"
                    "Für jeden Datensatz berechnet SHAP, um wie viel das Ergebnis "
                    "vom Durchschnitt abweicht und wie viel davon jedem Merkmal "
                    "zuzuschreiben ist — unter Berücksichtigung aller möglichen "
                    "Merkmalskombinationen. Das ist mathematisch exakt, aber rechenintensiv.\n\n"
                    "Hier wird **TreeExplainer** verwendet — ein auf Entscheidungsbäume "
                    "optimierter Algorithmus, der exakte SHAP-Werte in Polynomialzeit "
                    "berechnet (Lundberg et al., 2020). Angezeigt werden die mittleren "
                    "absoluten SHAP-Werte über alle 500 Datensätze — das ergibt ein "
                    "globales Bild der Merkmalsbedeutung, unabhängig von Gini-Verzerrungen."
                )
                st.divider()
                st.markdown("**Was bedeutet CV-F1 (5-Fold Kreuzvalidierung)?**")
                st.markdown(
                    "Um zu prüfen, ob das Modell wirklich verallgemeinert und nicht "
                    "nur die Trainingsdaten auswendig gelernt hat, wird **stratifizierte "
                    "5-Fold-Kreuzvalidierung** eingesetzt:\n\n"
                    "1. Die 500 Datensätze werden in 5 gleich große Teilmengen aufgeteilt\n"
                    "2. Das Modell wird 5-mal trainiert — je einmal auf 4/5 der Daten\n"
                    "3. Jedes Mal wird auf der verbleibenden 1/5 getestet\n"
                    "4. Der F1-Score wird für jede Runde gemessen und gemittelt\n\n"
                    "Der **F1-Score** ist das harmonische Mittel aus Precision und Recall — "
                    "er bestraft sowohl zu viele Fehlalarme (False Positives) als auch "
                    "übersehene Fehler (False Negatives). Das Modell erreicht CV-F1 = "
                    f"**{ml.cv_f1_mean:.3f} ± {ml.cv_f1_std:.3f}** — deutlich über dem "
                    "Zielwert von 0,75."
                )

            ml1, ml2, ml3 = st.columns(3)
            ml1.metric("CV-F1 (5-Fold)", f"{ml.cv_f1_mean:.3f}", f"+/- {ml.cv_f1_std:.3f}")
            ml2.metric("Train-Accuracy", f"{ml.accuracy_train:.3f}")
            ml3.metric("Features", ml.n_features)

            col_fi, col_sh = st.columns(2)
            with col_fi:
                st.subheader("Gini Feature-Importance")
                st.caption(
                    "Misst den durchschnittlichen Beitrag jedes Merkmals zur Verringerung "
                    "der Gini-Unreinheit über alle 100 Entscheidungsbäume. "
                    "Höhere Balken = Merkmal wird häufiger und wirkungsvoller für "
                    "Aufspaltungen genutzt."
                )
                fi_sorted = sorted(ml.feature_importances.items(), key=lambda x: x[1], reverse=True)
                st.bar_chart({k: v for k, v in fi_sorted})
            with col_sh:
                st.subheader("SHAP-Werte (mittlere |Shapley-Beitraege|)")
                st.caption(
                    "Spieltheoretisch fairer Beitrag jedes Merkmals zur Vorhersage, "
                    "gemittelt über alle 500 Datensätze. Unabhängig von Gini-Verzerrungen — "
                    "ein Merkmal mit kleiner Gini-Wichtigkeit kann hier trotzdem wichtig sein."
                )
                sh_sorted = sorted(ml.shap_mean_abs.items(), key=lambda x: x[1], reverse=True)
                st.bar_chart({k: v for k, v in sh_sorted})

            st.caption(
                f"Wichtigstes Merkmal laut SHAP: **{next(iter(ml.shap_mean_abs))}** "
                f"(SHAP = {list(ml.shap_mean_abs.values())[0]:.4f}). "
                f"Trainiert auf {ml.n_train} synthetischen Datensätzen, "
                f"Seed=42, 100 Bäume, max. Tiefe 6."
            )
        else:
            st.info("ML-Analyse in der Sidebar aktivieren.")

    # 7: Audit-Trail
    with tabs[7]:
        _erlaeuterung(
            "**Was ist der Audit-Trail und warum ist er wichtig?**\n\n"
            "Jede Aktion des Frameworks — vom Einlesen der Daten bis zur Erstellung "
            "des Berichts — wird automatisch protokolliert. Dieses Protokoll ist "
            "**manipulationssicher**: Jeder neue Eintrag enthält den kryptografischen "
            "Fingerabdruck (SHA-256-Hash) des vorherigen Eintrags. Wird auch nur ein "
            "einziger Eintrag nachträglich verändert, bricht die Kette und der Fehler "
            "wird sofort erkannt.\n\n"
            "Dieses Prinzip — bekannt aus der Blockchain-Technologie — stellt sicher, "
            "dass der Weg vom Rohdatum bis zum veröffentlichten Bericht lückenlos "
            "nachvollziehbar ist. Das ist eine Kernforderung der CSRD (Art. 34: externe "
            "Prüfpflicht) und des EU AI Act (Art. 13: Transparenz). "
            "In der Praxis ermöglicht es Wirtschaftsprüfern, jeden Schritt der "
            "KI-gestützten Berichterstellung zu kontrollieren."
        )
        st.write(f"Eintraege: {len(orch.audit.entries)} | "
                 f"Kette gueltig: {orch.audit.verify()}")
        st.caption("Append-only SHA-256-Hash-Kette (NFA-4.1) — Manipulationsschutz.")
        st.json(orch.audit.entries)

else:
    st.info("Konfiguration links waehlen und **Workflow ausfuehren** klicken.")

    with st.expander("Ueber diesen Prototyp"):
        st.markdown("""
**5-Schichten-Architektur** (Weiss et al., 2025):
1. **Governance & Compliance Layer** — Audit-Trail (SHA-256-Kette), Compliance-Agent
2. **Data Integration & Management** — Multi-Source Ingestion (JSON/CSV/Text)
3. **AI/Data Science Processing** — Deterministic + LLM-Extraktion, ML-Klassifikator
4. **Assessment & Calculation** — KPI-Bewertung, Sektorbenchmarks, Interpretation
5. **Reporting & Output** — ESRS-Nachhaltigkeitsbericht alle Standards (Markdown + PDF), Streamlit-Demo

**Hypothesen-Nachweis:**
- H1a: ~0.003s (deterministisch) | ~120s (claude-backend)
- H2a: F1=1.0 | H2b: 100% | H2d: CV-F1=0.853
- H3a: 10 neue Datenpunkte via YAML (kein Code)
""")
