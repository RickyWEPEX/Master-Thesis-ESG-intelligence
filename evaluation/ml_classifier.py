"""ML-Klassifikator fuer CSRD/ESRS-Compliance-Risiko (H2d, alle Standards).

Trainiert einen Random-Forest-Klassifikator auf synthetischen ESG-Daten
und erklaert Vorhersagen via SHAP (TreeExplainer). Implementiert Hypothese H2d:
automatisierte Risikoklassifikation mit akademisch sauberer Explainability.

Design-Entscheidungen:
- SHAP nur auf echten ML-Klassifikator, NICHT auf LLM-Ausgaben (vgl. CLAUDE.md)
- Seed=42 fuer vollstaendige Reproduzierbarkeit (QA-3.1)
- 20 Features aus allen wesentlichen ESRS-Standards (E1, E2, E3, E5, S1, S2, S4, G1)
- Synthetische Trainingsdaten mit bewusst erzeugten Regelverletungen
  (35% Fehlerklasse, 65% valide Daten) fuer ausgewogenes Training
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import shap
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

SEED = 42  # QA-3.1: fester Seed fuer Reproduzierbarkeit

# 20 quantitative ESRS-Merkmale aus allen wesentlichen Standards als Feature-Vektor
FEATURE_NAMES = [
    # E1 Klimawandel (10 Features)
    "scope_1_tco2e",
    "scope_2_market_tco2e",
    "scope_3_total_tco2e",
    "total_ghg_market_tco2e",
    "renewable_share_percent",
    "reduction_target_percent",
    "energy_intensity_mwh_per_mio_eur",
    "ghg_intensity_per_revenue",
    "assets_at_physical_risk_percent",
    "net_zero_years_remaining",
    # E2 Umweltverschmutzung
    "hazardous_waste_tonnes",
    # E3 Wasser
    "water_stress_area_withdrawal_percent",
    # E5 Ressourcen
    "recycling_rate_percent",
    # S1 Eigene Belegschaft
    "gender_pay_gap_percent",
    "injury_rate_per_1000_fte",
    "training_hours_per_fte",
    # S2 Wertschoepfungskette
    "high_risk_suppliers_percent",
    # S4 Verbraucher
    "customer_complaints_per_1000",
    # G1 Governance
    "compliance_violations_count",
    "anti_corruption_training_percent",
]

ERROR_RATIO = 0.35  # Anteil der Fehlerklasse im Trainingsdatensatz


@dataclass
class MLClassifierMetrics:
    """Evaluationsmetriken des ML-Klassifikators (H2d)."""

    accuracy_train: float
    cv_f1_mean: float
    cv_f1_std: float
    feature_importances: dict  # Gini-basierte Wichtigkeit (sortiert)
    shap_mean_abs: dict        # Mittlere absolute SHAP-Werte (sortiert)
    n_train: int
    n_features: int

    def to_dict(self) -> dict:
        return asdict(self)


def _generate_training_data(n_samples: int, seed: int) -> tuple:
    """Erzeugt synthetische ESG-Trainingsdaten (alle Standards) mit binaeren Labels.

    Label 0 = valider Datensatz (keine kritischen Regelverletzungen)
    Label 1 = fehlerhafter Datensatz (mindestens eine Regelverletzung)

    Fehlertypen (8 Typen, zyklisch verteilt):
    E1: 0=Summenregel, 1=Negativwert Scope1, 2=Reduktionsziel>100%, 3=Intensitaet>5000
    E2: 4=Gefaehrlicher Abfall > 5t (Ausreisser fuer Buero)
    S1: 5=Gender Pay Gap > 30%, 6=Verletzungsrate > 10/1000 FTE
    G1: 7=Compliance-Vorfaelle > 0 AND Antikorruptionstraining < 70%
    """
    rng = np.random.default_rng(seed)
    n_errors = int(n_samples * ERROR_RATIO)

    rows, labels = [], []
    for i in range(n_samples):
        # E1-Features (Basiswerte)
        scope1 = rng.uniform(500.0, 3000.0)
        scope2_market = rng.uniform(1000.0, 5000.0)
        scope3 = rng.uniform(50_000.0, 250_000.0)
        total_correct = scope1 + scope2_market + scope3
        renewable_share = rng.uniform(10.0, 90.0)
        reduction_target = rng.uniform(20.0, 80.0)
        energy_intensity = rng.uniform(60.0, 150.0)
        ghg_intensity = rng.uniform(500.0, 2000.0)
        assets_risk_pct = rng.uniform(1.0, 20.0)
        net_zero_remaining = float(rng.integers(10, 30))
        # E2-Features
        hazardous_waste = rng.uniform(0.2, 2.0)
        # E3-Features
        water_stress_pct = rng.uniform(0.0, 10.0)
        # E5-Features
        recycling_rate = rng.uniform(40.0, 90.0)
        # S1-Features
        gender_pay_gap = rng.uniform(3.0, 22.0)
        injury_rate = rng.uniform(0.5, 6.0)
        training_hours = rng.uniform(15.0, 55.0)
        # S2-Features
        high_risk_suppliers = rng.uniform(2.0, 20.0)
        # S4-Features
        customer_complaints = rng.uniform(1.5, 10.0)
        # G1-Features
        compliance_violations = 0.0
        anti_corruption_training = rng.uniform(75.0, 100.0)

        if i < n_errors:
            err = i % 8
            if err == 0:    # E1: Summenregel verletzt
                total_correct = total_correct * rng.uniform(0.82, 0.93)
            elif err == 1:  # E1: Negativwert
                scope1 = -abs(scope1)
            elif err == 2:  # E1: Reduktionsziel > 100%
                reduction_target = rng.uniform(105.0, 150.0)
            elif err == 3:  # E1: GHG-Intensitaet Ausreisser
                ghg_intensity = rng.uniform(6000.0, 15000.0)
            elif err == 4:  # E2: Gefaehrlicher Abfall Ausreisser
                hazardous_waste = rng.uniform(6.0, 20.0)
            elif err == 5:  # S1: Extremer Gender Pay Gap
                gender_pay_gap = rng.uniform(32.0, 55.0)
            elif err == 6:  # S1: Hohe Verletzungsrate
                injury_rate = rng.uniform(12.0, 25.0)
            else:           # G1: Compliance-Vorfaelle + schwaches Antikorruptionstraining
                compliance_violations = float(rng.integers(1, 5))
                anti_corruption_training = rng.uniform(30.0, 65.0)
            label = 1
        else:
            total_correct = total_correct * rng.uniform(0.995, 1.005)
            label = 0

        rows.append([
            scope1, scope2_market, scope3, total_correct,
            renewable_share, reduction_target, energy_intensity,
            ghg_intensity, assets_risk_pct, net_zero_remaining,
            hazardous_waste, water_stress_pct, recycling_rate,
            gender_pay_gap, injury_rate, training_hours,
            high_risk_suppliers, customer_complaints,
            compliance_violations, anti_corruption_training,
        ])
        labels.append(label)

    return np.array(rows, dtype=float), np.array(labels, dtype=int)


class ESRSComplianceClassifier:
    """Random-Forest-Klassifikator fuer ESRS-E1-Datenfehler-Erkennung.

    Klassifiziert ob ein Datensatz kritische Validierungsfehler aufweist.
    TreeExplainer liefert exakte SHAP-Werte fuer Baummodelle (H2d).
    """

    def __init__(self, n_estimators: int = 100, seed: int = SEED) -> None:
        self.clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=6,
            random_state=seed,
            class_weight="balanced",
        )
        self._explainer: shap.TreeExplainer | None = None
        self.feature_names = FEATURE_NAMES

    def fit(self, X: np.ndarray, y: np.ndarray) -> "ESRSComplianceClassifier":
        self.clf.fit(X, y)
        self._explainer = shap.TreeExplainer(self.clf)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.clf.predict(X)

    def feature_importance_dict(self) -> dict:
        importances = {
            name: round(float(imp), 4)
            for name, imp in zip(self.feature_names, self.clf.feature_importances_)
        }
        return dict(sorted(importances.items(), key=lambda kv: kv[1], reverse=True))

    def shap_mean_abs_dict(self, X: np.ndarray) -> dict:
        """Mittlere absolute SHAP-Werte ueber alle Instanzen in X (globale Wichtigkeit)."""
        sv = self._explainer.shap_values(X)
        # RandomForest gibt Liste [class0_sv, class1_sv] zurueck
        sv_class1 = sv[1] if isinstance(sv, list) else sv
        mean_abs = {
            name: round(float(np.mean(np.abs(sv_class1[:, i]))), 4)
            for i, name in enumerate(self.feature_names)
        }
        return dict(sorted(mean_abs.items(), key=lambda kv: kv[1], reverse=True))

    def cv_f1(self, X: np.ndarray, y: np.ndarray, cv: int = 5) -> tuple[float, float]:
        """Stratifizierte Kreuzvalidierung; gibt (mean_f1, std_f1) zurueck."""
        skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=SEED)
        scores = cross_val_score(self.clf, X, y, cv=skf, scoring="f1")
        return round(float(np.mean(scores)), 4), round(float(np.std(scores)), 4)


def run_ml_evaluation(n_samples: int = 500, seed: int = SEED) -> MLClassifierMetrics:
    """Vollstaendige H2d-Evaluation: Training, Kreuzvalidierung, SHAP.

    Gibt MLClassifierMetrics zurueck; deterministisch bei gleichem seed.
    """
    X, y = _generate_training_data(n_samples, seed)

    clf = ESRSComplianceClassifier(seed=seed)

    # Kreuzvalidierungs-F1 VOR finalem Training (echter Generalisierungsschaetzer)
    cv_mean, cv_std = clf.cv_f1(X, y)

    # Finales Training auf allen Daten fuer SHAP + Feature-Importance
    clf.fit(X, y)

    y_pred = clf.predict(X)
    accuracy = round(float(np.mean(y_pred == y)), 4)

    return MLClassifierMetrics(
        accuracy_train=accuracy,
        cv_f1_mean=cv_mean,
        cv_f1_std=cv_std,
        feature_importances=clf.feature_importance_dict(),
        shap_mean_abs=clf.shap_mean_abs_dict(X),
        n_train=n_samples,
        n_features=len(FEATURE_NAMES),
    )
