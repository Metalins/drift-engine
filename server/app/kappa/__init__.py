"""κ-engine — el núcleo único del producto.

⚠️ CRITICAL: este módulo es CLOSED SOURCE forever.
Este código nunca sale del server, ni siquiera en Docker images publicadas.

El flujo ACTIVO (enrolment + verify por challenges) sigue en STUB. El
engine V2 PASIVO (#62) — el DNA learner que consume behavioral metadata
y detecta drift distribucional — es real y se exporta abajo.
"""
from app.kappa.engine import (
    # Active enrolment / verify flow (Fase 1 stub).
    fingerprint_baseline,
    compare_to_baseline,
    generate_challenges,
    # V2 passive behavioral DNA learner (#62).
    fingerprint_behavioral_baseline,
    compare_behavioral_to_baseline,
    build_distributions,
    compare_distributions,
)

__all__ = [
    "fingerprint_baseline",
    "compare_to_baseline",
    "generate_challenges",
    "fingerprint_behavioral_baseline",
    "compare_behavioral_to_baseline",
    "build_distributions",
    "compare_distributions",
]
