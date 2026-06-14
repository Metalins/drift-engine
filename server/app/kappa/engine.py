"""κ-engine — active enrolment/verify stubs + V2 behavioral DNA learner.

Two distinct subsystems live here:

1. The **active** challenge/response flow (Fase 1 stub, unchanged):
   ``fingerprint_baseline`` / ``compare_to_baseline`` / ``generate_challenges``.
   These run at agent *registration* (compute an enrolment fingerprint) and
   at the *verify* endpoint (issue challenges, score responses). They are
   still stubs — the active high-assurance flow is a separate roadmap item.
   ⚠️ Their signatures are part of the contract with ``app/api/agents.py``
   and ``app/api/verify.py``; do not change them here.

2. The **passive** behavioral DNA learner — V2 (#62):
   ``fingerprint_behavioral_baseline`` / ``compare_behavioral_to_baseline``
   (+ the pure ``build_distributions`` / ``compare_distributions`` core).
   This is the real product engine. It is PASSIVE: it watches organic
   traffic (no challenges), learns a per-agent baseline distribution over
   the behavioral features the SDK ships (#63), and detects drift by
   comparing a fresh window of traffic to that baseline.

Why the V2 functions don't reuse the names ``fingerprint_baseline`` /
``compare_to_baseline``: those names are already bound, with different
signatures, to the active flow above. Reusing them would break agent
registration and the verify endpoint. The V2 engine is a genuinely
different concept (passive distributional drift, not active
challenge-response), so it gets its own descriptive names.

The V2 model
------------
The server only stores hashes of an agent's input/output, so it cannot
see content. What it CAN see — because the SDK computes them client-side
and ships them as ``metadata_json['behavioral']`` — is a bag of
low-resolution, hard-to-invert *structural* features per event:
output/input lengths, a token estimate, format markers, sentence stats,
tool calls, latency, error class, and a keyed locality-sensitive token hash.

V2 learns a baseline distribution per feature, then compares a window
with standard two-sample statistics:

  - continuous (lengths, latency, sentence stats): Kolmogorov–Smirnov
    statistic (already in [0,1]) as the drift score; Wasserstein
    distance for attribution magnitude.
  - discrete/categorical (error_class, boolean format markers, tool-name
    distribution): chi-squared with Laplace smoothing → 1 − p_value.
  - token_bag_lsh: mean minimum Hamming distance of the window's
    fingerprints to the baseline set, normalized by the bit width.

``drift_score = max(per-feature scores)`` — the single most out-of-baseline
feature drives the verdict and is reported as ``dominant_feature`` with an
attribution summary.

CRITICAL: este módulo es CLOSED SOURCE. No sale del server. No hay binario
del cliente que lo contenga.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from typing import Any, Optional, Sequence

import numpy as np
from scipy.stats import chi2_contingency, ks_2samp, wasserstein_distance

from app.kappa.behavioral_schema import BOOL_FEATURES, CONTINUOUS_FEATURES

# Below this drift score the agent's recent behavior is considered
# consistent with its baseline (``verified=True``). Tuned for V0.1; the
# alerts pipeline (#64) can apply a per-customer threshold on top.
DRIFT_THRESHOLD = 0.5

# Bit width of the SDK's token_bag_lsh SimHash (16 hex chars).
_LSH_BITS = 64

# A continuous feature needs at least this many window samples before its
# KS statistic is trustworthy — a window of 1-2 produces a noisy verdict.
MIN_CONTINUOUS_WINDOW = 8

BASELINE_VERSION = "v2-0.1"


# =========================================================================== #
# Active flow — Fase 1 STUB. Signatures are contracts with agents.py /        #
# verify.py. DO NOT change these signatures here.                             #
# =========================================================================== #

def _stable_hash(payload: dict[str, Any]) -> str:
    """Hash determinístico de un payload JSON. Helper interno."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_baseline(metadata: dict[str, Any], behavior_samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Genera el κ-fingerprint de ENROLMENT durante el registro del agent.

    STUB (active flow): hash determinístico de metadata + samples. Lo
    consume ``app/api/agents.py::register_agent`` para poblar
    ``Agent.baseline_kappa`` + ``enrolment_score``. La firma estructural
    real (marco U⊕κ⊕τ) es un item de roadmap aparte; el engine V2 pasivo
    (#62) vive en ``fingerprint_behavioral_baseline`` más abajo.
    """
    fingerprint_hash = _stable_hash({"metadata": metadata, "samples": behavior_samples})
    score = 0.99  # stub: enrolment exitoso siempre con high score

    return {
        "version": "stub-1",
        "fingerprint_hash": fingerprint_hash,
        "n_samples": len(behavior_samples),
        "enrolment_score": score,
    }


def compare_to_baseline(
    baseline: dict[str, Any],
    metadata: dict[str, Any],
    responses: list[dict[str, Any]],
    *,
    steps: int = 1,
) -> dict[str, Any]:
    """Compara respuestas a challenges contra el baseline de enrolment.

    STUB (active flow): re-hashing simple sobre la forma de las
    responses. Lo consume ``app/api/verify.py``. La comparación
    distribucional real del producto es el engine V2 pasivo (#62) en
    ``compare_behavioral_to_baseline`` más abajo.
    """
    if not responses:
        return {"verified": False, "score": 0.0, "reason": "no_responses"}

    valid_responses = [
        r for r in responses
        if isinstance(r, dict) and "challenge_id" in r and "response" in r
    ]

    score = len(valid_responses) / max(len(responses), 1)
    if steps > 1:
        score = score ** (1.0 / steps)

    verified = score >= 0.7

    return {
        "verified": verified,
        "score": float(score),
        "steps": steps,
        "n_valid_responses": len(valid_responses),
        "n_total_responses": len(responses),
    }


def generate_challenges(baseline: dict[str, Any], n: int = 1) -> list[dict[str, Any]]:
    """Genera N challenges fresh. STUB — V2 es pasivo; los challenges
    activos multi-step son una capa aparte (board.json #62: "dejar el stub
    vigente"). Firma estable para el SDK / callers.
    """
    challenges = []
    for i in range(n):
        challenge_id = f"ch_{secrets.token_urlsafe(16)}"
        payload = secrets.token_urlsafe(32)
        challenges.append({
            "id": challenge_id,
            "payload": payload,
            "step": i + 1,
            "depends_on": challenges[i - 1]["id"] if i > 0 else None,
        })
    return challenges


# =========================================================================== #
# V2 passive engine — pure feature math (operates on lists of behavioral      #
# dicts; no DB). This is the unit-testable core.                              #
# =========================================================================== #

def _continuous_values(samples: Sequence[dict], feature: str) -> list[float]:
    """Pull a continuous feature's values, dropping missing / None."""
    out: list[float] = []
    for s in samples:
        v = s.get(feature)
        if isinstance(v, bool):  # guard: bools are ints in Python
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _categorical_counts(values: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        key = str(v)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _window_tool_tokens(window_samples: Sequence[dict]) -> list[str]:
    """Flatten tool_calls per turn, tagging tool-less turns as __none__."""
    out: list[str] = []
    for s in window_samples:
        tc = s.get("tool_calls")
        if isinstance(tc, list) and tc:
            out.extend(str(t) for t in tc)
        else:
            out.append("__none__")
    return out


def _tool_bigrams(samples: Sequence[dict]) -> list[str]:
    """Consecutive tool→tool transitions within each turn's tool_calls.

    A turn calling [a, b, c] yields "a>b", "b>c". Captures ordering /
    transition drift (e.g. an agent that starts chaining tools in a new
    order) that a flat tool-name frequency misses — spec #62 requires
    "distribución de tool name + bigrams tool→tool".
    """
    out: list[str] = []
    for s in samples:
        tc = s.get("tool_calls")
        if isinstance(tc, list) and len(tc) >= 2:
            names = [str(t) for t in tc]
            out.extend(f"{a}>{b}" for a, b in zip(names, names[1:]))
    return out


def build_distributions(samples: Sequence[dict]) -> dict[str, Any]:
    """Compute the baseline distribution summary from behavioral samples.

    Stores both summary stats (for attribution / display) AND the raw
    value arrays the two-sample tests need at compare time. Sample arrays
    are bounded by ``n_events`` upstream, so the JSON stays small.
    """
    dist: dict[str, Any] = {"continuous": {}, "categorical": {}, "lsh": {}}

    for feat in CONTINUOUS_FEATURES:
        vals = _continuous_values(samples, feat)
        if not vals:
            continue
        arr = np.asarray(vals, dtype=float)
        dist["continuous"][feat] = {
            "samples": vals,
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "percentiles": {
                "p25": float(np.percentile(arr, 25)),
                "p50": float(np.percentile(arr, 50)),
                "p75": float(np.percentile(arr, 75)),
                "p90": float(np.percentile(arr, 90)),
                "p99": float(np.percentile(arr, 99)),
            },
            "n": len(vals),
        }

    # Boolean format markers → 2-category frequency.
    for feat in BOOL_FEATURES:
        vals = [bool(s[feat]) for s in samples if feat in s]
        if vals:
            dist["categorical"][feat] = _categorical_counts(vals)

    # error_class categorical frequency.
    ec = [s["error_class"] for s in samples if "error_class" in s]
    if ec:
        dist["categorical"]["error_class"] = _categorical_counts(ec)

    # tool_calls: tool-name frequency (with __none__ for tool-less turns)
    # plus tool→tool bigrams for transition/ordering drift.
    tool_names = _window_tool_tokens(samples)
    if tool_names:
        dist["categorical"]["tool_calls"] = _categorical_counts(tool_names)
    bigrams = _tool_bigrams(samples)
    if bigrams:
        dist["categorical"]["tool_bigrams"] = _categorical_counts(bigrams)

    # token_bag_lsh: keep the distinct fingerprints seen.
    lsh_set = sorted({
        s["token_bag_lsh"]
        for s in samples
        if isinstance(s.get("token_bag_lsh"), str) and s["token_bag_lsh"]
    })
    if lsh_set:
        dist["lsh"]["fingerprints"] = lsh_set

    return dist


def _score_continuous(
    baseline_vals: Sequence[float], window_vals: Sequence[float]
) -> Optional[dict[str, Any]]:
    if len(baseline_vals) < 2 or len(window_vals) < MIN_CONTINUOUS_WINDOW:
        return None
    ks = ks_2samp(baseline_vals, window_vals)
    try:
        emd = float(wasserstein_distance(baseline_vals, window_vals))
    except Exception:
        emd = 0.0
    return {
        "score": float(ks.statistic),  # already in [0, 1]
        "test": "ks_2samp",
        "magnitude": emd,
        "baseline_mean": float(np.mean(baseline_vals)),
        "current_mean": float(np.mean(window_vals)),
    }


def _score_categorical(
    baseline_counts: dict[str, int], window_values: Sequence[Any]
) -> Optional[dict[str, Any]]:
    """Categorical drift as TOTAL VARIATION DISTANCE — a bounded [0,1]
    effect size, not a significance probability.

    The earlier version used ``1 - p_value`` from a chi-squared test. A
    p-value measures *significance*, which saturates toward 1.0 with
    sample size / sampling noise, so an identical agent produced false
    drift (~45% of the time per feature) and the verdict's ``max()``
    aggregation was dominated by that noise. Total variation distance —
    ``0.5 * Σ|p_i - q_i|`` over the normalized distributions — is an
    effect size on the same [0,1] scale as the KS and Hamming scores, so
    all per-feature scores are now comparable and noise-stable. The
    chi-squared p-value is kept only as supplementary attribution detail.
    """
    if not window_values:
        return None
    window_counts = _categorical_counts([str(v) for v in window_values])
    categories = sorted(set(baseline_counts) | set(window_counts))
    if len(categories) < 2:
        # Only one category ever observed → no contrast, no drift signal.
        return {
            "score": 0.0,
            "test": "tvd",
            "baseline_dist": dict(baseline_counts),
            "current_dist": window_counts,
        }

    base_total = sum(baseline_counts.values()) or 1
    win_total = sum(window_counts.values()) or 1
    tvd = 0.5 * sum(
        abs(baseline_counts.get(c, 0) / base_total - window_counts.get(c, 0) / win_total)
        for c in categories
    )

    # Supplementary significance signal (attribution only), Laplace-smoothed.
    p_value = None
    try:
        table = np.array([
            [baseline_counts.get(c, 0) + 1 for c in categories],
            [window_counts.get(c, 0) + 1 for c in categories],
        ], dtype=float)
        _, p_value, _, _ = chi2_contingency(table)
        p_value = float(p_value)
    except Exception:
        p_value = None

    return {
        "score": float(max(0.0, min(1.0, tvd))),
        "test": "tvd",
        "p_value": p_value,
        "baseline_dist": dict(baseline_counts),
        "current_dist": window_counts,
    }


def _score_lsh(
    baseline_fingerprints: Sequence[str], window_samples: Sequence[dict]
) -> Optional[dict[str, Any]]:
    window_lsh = [
        s["token_bag_lsh"]
        for s in window_samples
        if isinstance(s.get("token_bag_lsh"), str) and s["token_bag_lsh"]
    ]
    if not baseline_fingerprints or not window_lsh:
        return None
    base_ints = [int(h, 16) for h in baseline_fingerprints]
    dists = []
    for h in window_lsh:
        wi = int(h, 16)
        dists.append(min(_hamming(wi, bi) for bi in base_ints))
    mean_min = float(np.mean(dists))
    return {
        "score": float(max(0.0, min(1.0, mean_min / _LSH_BITS))),
        "test": "hamming",
        "mean_min_hamming": mean_min,
    }


def compare_distributions(
    baseline: dict[str, Any], window_samples: Sequence[dict]
) -> dict[str, Any]:
    """Compare a fresh window of behavioral samples against a baseline.

    Returns the verdict dict: ``verified``, ``drift_score``,
    ``dominant_feature``, ``attribution`` (the dominant feature's
    baseline-vs-current summary), plus the full per-feature ``scores``.
    """
    scores: dict[str, dict[str, Any]] = {}

    cont = baseline.get("continuous", {})
    for feat, summary in cont.items():
        res = _score_continuous(
            summary.get("samples", []), _continuous_values(window_samples, feat)
        )
        if res is not None:
            scores[feat] = res

    cat = baseline.get("categorical", {})
    for feat, counts in cat.items():
        if feat in BOOL_FEATURES:
            window_vals = [bool(s[feat]) for s in window_samples if feat in s]
        elif feat == "error_class":
            window_vals = [s["error_class"] for s in window_samples if "error_class" in s]
        elif feat == "tool_calls":
            window_vals = _window_tool_tokens(window_samples)
        elif feat == "tool_bigrams":
            window_vals = _tool_bigrams(window_samples)
        else:
            continue
        res = _score_categorical(counts, window_vals)
        if res is not None:
            scores[feat] = res

    lsh = baseline.get("lsh", {}).get("fingerprints")
    if lsh:
        res = _score_lsh(lsh, window_samples)
        if res is not None:
            scores["token_bag_lsh"] = res

    if not scores:
        return {
            "verified": False,
            "drift_score": 0.0,
            "dominant_feature": None,
            "attribution": {},
            "scores": {},
            "reason": "no_comparable_features",
        }

    dominant_feature = max(scores, key=lambda f: scores[f]["score"])
    drift_score = float(scores[dominant_feature]["score"])

    attribution = {
        "feature_name": dominant_feature,
        "magnitude": scores[dominant_feature].get(
            "magnitude", scores[dominant_feature].get("score")
        ),
        "detail": scores[dominant_feature],
    }

    return {
        "verified": drift_score < DRIFT_THRESHOLD,
        "drift_score": drift_score,
        "dominant_feature": dominant_feature,
        "attribution": attribution,
        "scores": {f: scores[f]["score"] for f in scores},
    }


# =========================================================================== #
# V2 passive engine — DB wrappers (query event_logs, persist/read             #
# AgentBaseline).                                                              #
# =========================================================================== #

def _load_behavioral_samples(db, agent_id: str, limit: int) -> list[dict]:
    """Load up to `limit` most-recent events' behavioral feature blobs.

    Events without behavioral metadata (pre-#63) are skipped.
    """
    from app.db.models import EventLog

    rows = (
        db.query(EventLog)
        .filter(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.desc())
        .limit(limit)
        .all()
    )
    samples: list[dict] = []
    for r in rows:
        md = r.metadata_json
        if isinstance(md, dict):
            beh = md.get("behavioral")
            if isinstance(beh, dict):
                samples.append(beh)
    return samples


def fingerprint_behavioral_baseline(db, agent_id: str, n_events: int = 200) -> dict[str, Any]:
    """Compute and persist the behavioral baseline for an agent (V2, #62).

    Reads the last ``n_events`` events' ``metadata_json['behavioral']``,
    builds the per-feature distributions, and upserts an ``AgentBaseline``
    row. Returns the baseline payload (also the persisted ``features_json``).
    """
    from app.db.models import AgentBaseline

    samples = _load_behavioral_samples(db, agent_id, n_events)
    features = build_distributions(samples)
    payload = {"version": BASELINE_VERSION, "features": features}

    row = (
        db.query(AgentBaseline)
        .filter(AgentBaseline.agent_id == agent_id)
        .first()
    )
    if row is None:
        row = AgentBaseline(agent_id=agent_id)
        db.add(row)
    row.features_json = payload
    row.n_events = len(samples)
    row.computed_at = datetime.utcnow()
    db.commit()

    return {
        "version": BASELINE_VERSION,
        "agent_id": agent_id,
        "n_events": len(samples),
        "features": features,
    }


def compare_behavioral_to_baseline(db, agent_id: str, window_size: int = 50) -> dict[str, Any]:
    """Compare an agent's recent window of traffic to its stored baseline (V2).

    Returns ``{verified, drift_score, dominant_feature, attribution, ...}``.
    If no baseline exists yet (or it has no comparable features), returns a
    not-verified verdict with a ``reason`` rather than raising.
    """
    from app.db.models import AgentBaseline

    row = (
        db.query(AgentBaseline)
        .filter(AgentBaseline.agent_id == agent_id)
        .first()
    )
    if row is None or not isinstance(row.features_json, dict):
        return {
            "verified": False,
            "drift_score": 0.0,
            "dominant_feature": None,
            "attribution": {},
            "scores": {},
            "reason": "no_baseline",
        }

    features = row.features_json.get("features", {})
    window = _load_behavioral_samples(db, agent_id, window_size)
    if not window:
        return {
            "verified": False,
            "drift_score": 0.0,
            "dominant_feature": None,
            "attribution": {},
            "scores": {},
            "reason": "no_window_events",
        }

    verdict = compare_distributions(features, window)
    verdict["agent_id"] = agent_id
    verdict["window_size"] = len(window)
    verdict["baseline_n_events"] = row.n_events
    return verdict
