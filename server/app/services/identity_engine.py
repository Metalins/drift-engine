"""Identity Engine — computes Trinity observables (ICR, TWC, TTM) over event logs.

Ported from `research/R4-computational-validation/code/observables.py` and
`observables_r6.py`, with two production-grade adaptations:

  1. Alphabet sizes are derived from the trace itself, not imported from a
     synthetic agent module (CHI/SIGMA constants are gone).
  2. Inputs are taken from the (input_hash, output_hash) columns of
     `event_logs` and bucketed into integer symbols deterministically.

The math is identical to the research code; only the I/O wrapping changed.

Sprint 1 scope:
  - compute_icr (R4) — Identity Conservation Ratio = MI(X, Y) / H(X)
  - compute_twc (R4 + R3.5-A Crooks calibration) — coupling free energy
  - compute_ttm (R6) — spectral gap of empirical transition operator

Each function is zero-hyperparameter at the level of identity (no thresholds);
window sizes and projections are derived from data.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np


# --------------------------------------------------------------------------- #
# Symbol extraction from event_logs                                           #
# --------------------------------------------------------------------------- #

# Number of buckets we project hashes into. This is the EFFECTIVE alphabet
# size used downstream. Picked so TTM transition matrices are tractable
# (32×32) yet have enough resolution; matches `project_mod=32` from R4.
DEFAULT_ALPHABET = 32


# --------------------------------------------------------------------------- #
# Tunable parameters (D-PROD.12)                                              #
# --------------------------------------------------------------------------- #
# Defaults below are LIBERAL — optimized for natural usage feeling like a
# working product within a week. Customers requiring higher assurance can
# raise them via the tunables endpoint (roadmap). Full table:
# docs/product/TUNABLE-PARAMETERS.md
#
# Bumping these makes the curve slower (stronger but feels conservative).
# Never lower MVS_VETO_THRESHOLD — security floor.

VOLUME_SATURATION_TAU = 100   # n events at which volume factor reaches ~63%
MVS_VETO_THRESHOLD = 0.7      # below this, MVS hard-caps confidence (clone signal)
MVS_BOOST_THRESHOLD = 0.9     # above this, MVS gives multiplicative boost


def _hash_to_symbol(hex_hash: str, modulus: int = DEFAULT_ALPHABET) -> int:
    """Bucket a hex digest into [0, modulus) deterministically.

    Uses first 8 hex chars (32 bits) → int → mod. Same digest → same symbol,
    so the alphabet is stable across runs and across agents reporting the
    same content.
    """
    if not hex_hash:
        return 0
    # Take first 8 hex chars for a 32-bit integer; mod into alphabet.
    h = hex_hash.strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    try:
        n = int(h[:8], 16)
    except ValueError:
        # Fallback: sha256 of the raw string.
        n = int(hashlib.sha256(hex_hash.encode("utf-8")).hexdigest()[:8], 16)
    return n % modulus


def events_to_traces(
    events: Sequence[dict],
    alphabet: int = DEFAULT_ALPHABET,
) -> tuple[list[int], list[int]]:
    """Turn an ordered sequence of event-log rows into traces (X, Y).

    Each event dict must contain `input_hash` and `output_hash`. The result is:
      X = bucketed input symbols (the agent's "challenge"/context)
      Y = bucketed output symbols (the agent's "response")

    Order is the caller's responsibility (sort by event_count or ts before
    calling).
    """
    X = [_hash_to_symbol(e.get("input_hash", ""), alphabet) for e in events]
    Y = [_hash_to_symbol(e.get("output_hash", ""), alphabet) for e in events]
    return X, Y


# --------------------------------------------------------------------------- #
# Information-theoretic helpers (verbatim from research)                      #
# --------------------------------------------------------------------------- #

def _empirical_probs(seq: Iterable[int]) -> dict[int, float]:
    c = Counter(seq)
    n = sum(c.values())
    if n == 0:
        return {}
    return {k: v / n for k, v in c.items()}


def _shannon_entropy_from_probs(probs: Iterable[float]) -> float:
    return -sum(p * math.log(p) for p in probs if p > 0)


def _joint_seq(X: Sequence[int], Y: Sequence[int]) -> list[tuple[int, int]]:
    return list(zip(X, Y))


# --------------------------------------------------------------------------- #
# ICR — Identity Conservation Ratio                                           #
# --------------------------------------------------------------------------- #

# Sprint UX-5.12 — sample-size floors for honest ICR reporting (see
# docs/product/TWO-LAYER-TRUST-DESIGN.md §2.5 and the Exp-CvD verdict in
# tests/synthetic/experiments/content-vs-distribution/VERDICT.md).
#
# Below BEHAVIORAL_ICR_FLOOR, MI estimates are dominated by finite-sample
# bias — even cryptographically independent X, Y produce ICR ≈ 0.5 at
# N=200. We refuse to report a number in that regime; `compute_icr`
# returns None and downstream surfaces show "not enough data" to the
# customer instead of fabricating confidence.
#
# At BEHAVIORAL_ICR_STABLE we believe the magnitude (after Miller-Madow
# correction), so the second layer of trust can graduate to "stable".
BEHAVIORAL_ICR_FLOOR = 2000
BEHAVIORAL_ICR_STABLE = 5000


def compute_icr(X: Sequence[int], Y: Sequence[int]) -> float | None:
    """ICR = (MI(X, Y) - bias) / H(X), with Miller-Madow correction.

    Returns:
      None    — N < BEHAVIORAL_ICR_FLOOR. Sample is too small for the MI
                estimator to be trusted. Callers MUST treat this as "not
                enough data" and NOT substitute 0.0 (Sprint UX-5.12 §5.1).
      [0, 1]  — corrected ICR. Negative raw values (real bias > real MI)
                are clamped to 0 since ratios are conceptually [0, 1].

    Math:
      MI_raw = sum p(x,y) log(p(x,y) / (p(x)·p(y)))
      bias   = (K_xy - K_x - K_y + 1) / (2N)   [Miller-Madow]
      MI     = max(0, MI_raw - bias)
      ICR    = MI / H(X)

    Pre-Sprint UX-5.12 this function returned the uncorrected raw value
    for any N ≥ 4. The Exp-CvD experiment showed that produced ICR ≈ 0.47
    for crypto-independent traffic at N=200, which then drove
    identity_confidence to ~0.47 — a literal random emitter looked
    half-trusted. The fix is mathematical (correction) and methodological
    (refuse to report below the floor).
    """
    if len(X) != len(Y):
        return None
    n = len(X)
    if n < BEHAVIORAL_ICR_FLOOR:
        return None

    p_x = _empirical_probs(X)
    p_y = _empirical_probs(Y)
    p_xy = _empirical_probs(_joint_seq(X, Y))

    mi_raw = 0.0
    for (x, y), p in p_xy.items():
        if p > 0 and p_x.get(x, 0) > 0 and p_y.get(y, 0) > 0:
            mi_raw += p * math.log(p / (p_x[x] * p_y[y]))

    # Miller-Madow finite-sample bias correction.
    k_x = len(p_x)
    k_y = len(p_y)
    k_xy = len(p_xy)
    bias_estimate = (k_xy - k_x - k_y + 1) / (2.0 * n)
    mi = max(0.0, mi_raw - bias_estimate)

    h_x = _shannon_entropy_from_probs(p_x.values())
    if h_x <= 0:
        return 0.0
    return min(1.0, mi / h_x)


# --------------------------------------------------------------------------- #
# TWC — Thermodynamic Work of Coupling (Crooks-calibrated)                    #
# --------------------------------------------------------------------------- #

def _kl_cost(symbol: int, p_obs: dict, p_base: dict, floor: float = 1e-9) -> float:
    po = p_obs.get(symbol, floor)
    pb = p_base.get(symbol, floor)
    if po <= 0 or pb <= 0:
        return 0.0
    return float(math.log(po / pb))


def _crooks_calibrate_beta(works: np.ndarray, fallback: float = 1.0) -> float:
    """Estimate β from Crooks symmetry log P(+W)/P(-W) = β W.

    Returns `fallback` if too little data or degenerate distribution.
    Clipped to [0.1, 10.0].
    """
    if len(works) < 20:
        return fallback
    works = works[np.isfinite(works)]
    if len(works) < 20 or works.std() == 0:
        return fallback

    abs_max = np.abs(works).max()
    if abs_max < 1e-6:
        return fallback

    nbins = min(20, max(5, len(works) // 5))
    bins = np.linspace(-abs_max, abs_max, nbins + 1)
    hist, edges = np.histogram(works, bins=bins)
    centers = 0.5 * (edges[:-1] + edges[1:])

    half = nbins // 2
    ratios: list[float] = []
    ws: list[float] = []
    for i in range(half):
        ix_pos = nbins - 1 - i
        ix_neg = i
        p_pos = hist[ix_pos]
        p_neg = hist[ix_neg]
        if p_pos > 0 and p_neg > 0:
            ratios.append(float(np.log(p_pos / p_neg)))
            ws.append(float(centers[ix_pos]))
    if len(ratios) < 3:
        return fallback

    slope, _ = np.polyfit(ws, ratios, 1)
    return float(max(0.1, min(10.0, slope)))


def compute_twc(
    X: Sequence[int],
    Y: Sequence[int],
    baseline_fraction: float = 0.2,
    segment_size: int = 200,
) -> tuple[float, float]:
    """TWC = log(Z_XY / (Z_X · Z_Y)) / β.

    Returns (TWC_in_nats, beta). β is calibrated by Crooks symmetry over
    segment-averaged works; falls back to 1.0 if insufficient data.

    Distinguishes real coupling (TWC strongly positive) from independence
    (TWC ≈ 0) — and is mathematically *not* equal to MI(X, Y), which the
    R4-Q1 sub-experiment verifies.
    """
    n = len(X)
    if n != len(Y) or n <= max(50, int(baseline_fraction * n)) + segment_size:
        return 0.0, 1.0

    n_base = max(50, int(baseline_fraction * n))
    X_base, Y_base = X[:n_base], Y[:n_base]
    X_obs, Y_obs = X[n_base:], Y[n_base:]

    p_base_X = _empirical_probs(X_base)
    p_base_Y = _empirical_probs(Y_base)
    p_base_XY = _empirical_probs(_joint_seq(X_base, Y_base))
    p_obs_X = _empirical_probs(X_obs)
    p_obs_Y = _empirical_probs(Y_obs)
    p_obs_XY = _empirical_probs(_joint_seq(X_obs, Y_obs))

    works: list[float] = []
    for i in range(0, len(X_obs) - segment_size, segment_size):
        seg_x = X_obs[i : i + segment_size]
        seg_y = Y_obs[i : i + segment_size]
        w = 0.0
        for x in seg_x:
            w += _kl_cost(x, p_obs_X, p_base_X)
        for y in seg_y:
            w += _kl_cost(y, p_obs_Y, p_base_Y)
        works.append(w / (2 * segment_size))
    works_arr = np.array(works)
    beta = _crooks_calibrate_beta(works_arr)

    alphabet_X = set(X_base) | set(X_obs)
    alphabet_Y = set(Y_base) | set(Y_obs)
    alphabet_XY = set(p_base_XY.keys()) | set(p_obs_XY.keys())

    log_Z_X = float(np.log(sum(
        np.exp(-beta * _kl_cost(x, p_obs_X, p_base_X)) for x in alphabet_X
    )))
    log_Z_Y = float(np.log(sum(
        np.exp(-beta * _kl_cost(y, p_obs_Y, p_base_Y)) for y in alphabet_Y
    )))
    log_Z_XY = float(np.log(sum(
        np.exp(-beta * _kl_cost(xy, p_obs_XY, p_base_XY)) for xy in alphabet_XY
    )))

    f_coupling = -(log_Z_XY - log_Z_X - log_Z_Y) / beta
    twc = -f_coupling
    return float(twc), float(beta)


# --------------------------------------------------------------------------- #
# TTM — Thermal Time Modular (Connes–Rovelli spectral gap)                    #
# --------------------------------------------------------------------------- #

def compute_ttm(Y: Sequence[int], alphabet: int = DEFAULT_ALPHABET) -> float:
    """TTM: spectral gap of the empirical transition operator on the response
    alphabet.

    Approximates the modular automorphism generator of the agent's empirical
    KMS state. Two agents with same params but distinct seeds have nearly
    identical transition operators but slightly different spectral gaps —
    TTM amplifies that difference, which is why it dominates the perfect-
    clone detection regime.

    Returns 0.0 if there isn't enough data to estimate.
    """
    if len(Y) < 100:
        return 0.0

    T = np.zeros((alphabet, alphabet))
    for i in range(len(Y) - 1):
        a, b = int(Y[i]) % alphabet, int(Y[i + 1]) % alphabet
        T[a, b] += 1
    row_sums = T.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    T = T / row_sums

    try:
        eigs = np.linalg.eigvals(T)
        eigs_sorted = sorted(np.abs(eigs), reverse=True)
        if len(eigs_sorted) >= 2:
            return float(eigs_sorted[0] - eigs_sorted[1])
    except np.linalg.LinAlgError:
        return 0.0
    return 0.0


# --------------------------------------------------------------------------- #
# Aggregator                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class TrinityResult:
    """One snapshot of Trinity observables over a window of events."""
    icr: float | None
    twc: float | None
    ttm: float | None
    beta_crooks: float | None
    n_events: int
    identity_confidence: float  # 0.0–1.0
    details: dict = field(default_factory=dict)

    def to_db_kwargs(self) -> dict:
        return {
            "icr": self.icr,
            "twc": self.twc,
            "ttm": self.ttm,
            "beta_crooks": self.beta_crooks,
            "n_events": self.n_events,
            "identity_confidence": self.identity_confidence,
            "details_json": self.details,
        }


def compute_trinity(
    events: Sequence[dict],
    alphabet: int = DEFAULT_ALPHABET,
) -> TrinityResult:
    """Compute ICR, TWC, TTM + identity_confidence over an ordered window of events.

    `events` is an ordered sequence of dicts with keys `input_hash`, `output_hash`.
    Caller is responsible for ordering (by event_count or ts).
    """
    n = len(events)
    if n == 0:
        return TrinityResult(None, None, None, None, 0, 0.0, {"reason": "no_events"})

    X, Y = events_to_traces(events, alphabet=alphabet)

    icr = compute_icr(X, Y) if n >= 4 else None
    twc_val: float | None = None
    beta_val: float | None = None
    if n >= max(50, int(0.2 * n)) + 200:
        twc_val, beta_val = compute_twc(X, Y)
    ttm = compute_ttm(Y, alphabet=alphabet) if n >= 100 else None

    confidence = identity_confidence_v0(icr, twc_val, ttm, n)

    return TrinityResult(
        icr=icr,
        twc=twc_val,
        ttm=ttm,
        beta_crooks=beta_val,
        n_events=n,
        identity_confidence=confidence,
        details={"alphabet": alphabet},
    )


# --------------------------------------------------------------------------- #
# Identity Confidence v0                                                      #
# --------------------------------------------------------------------------- #

def identity_confidence_v1(
    icr: float | None,
    twc: float | None,
    ttm: float | None,
    mvs: float | None,
    n_events: int,
    rks: float | None = None,
    tls: float | None = None,
    adv: float | None = None,
    prs: float | None = None,
    mcs: float | None = None,
    zkh: float | None = None,
) -> float:
    """Sprint 2 aggregator — Trinity + MVS, ICR-gated.

    Adds MVS to the v0 formula with two important properties:

      1. **MVS as veto signal.** If MVS is decisively low (<0.7), the
         confidence is hard-capped — this is the clone-perfect detection
         path (R7.b: AUC 1.0). Even with strong ICR/TWC/TTM, an agent
         that fails memory probes is suspect.

      2. **MVS as boost.** When MVS is high (>0.9), it sharpens the
         ICR-driven score by adding up to ~+0.2 multiplicatively.

    Sprint 7 — RKS added as a HARD veto (no boost path). Legitimate
    signature failure rate is 0%, so any non-trivial drop (e.g.
    rks < 0.95) caps the confidence at the rks value itself. There is
    no "rks high = boost" because a perfect signature is the expected
    baseline, not a positive signal.

    Returns 0.0 when n_events == 0 or there is no ICR signal.
    """
    base = identity_confidence_v0(icr, twc, ttm, n_events)
    if base == 0.0:
        return base

    # MVS branch (Sprint 2).
    if mvs is not None:
        mvs = max(0.0, min(1.0, mvs))
        if mvs < MVS_VETO_THRESHOLD:
            # 0.0 at mvs=0, scaling up to base*0.5 at MVS_VETO_THRESHOLD
            base = min(base, base * (mvs / MVS_VETO_THRESHOLD) * 0.5)
        elif mvs < MVS_BOOST_THRESHOLD:
            soft_span = MVS_BOOST_THRESHOLD - MVS_VETO_THRESHOLD
            base = base * (0.85 + 0.15 * (mvs - MVS_VETO_THRESHOLD) / soft_span)
        else:
            boost_span = 1.0 - MVS_BOOST_THRESHOLD
            base = min(
                1.0,
                base * (1.0 + 0.2 * (mvs - MVS_BOOST_THRESHOLD) / boost_span),
            )

    # RKS branch (Sprint 7). Hard cap, no boost.
    if rks is not None:
        rks = max(0.0, min(1.0, rks))
        # Any signature failure is a smoking gun — cap the score at the
        # fraction of valid signatures. Perfect chain (rks=1.0) leaves
        # `base` unchanged. Forked chain (rks=0.5) caps at 0.5.
        base = min(base, rks)

    # TLS branch (Sprint 7). Softer than RKS because the window is small
    # and an honest agent CAN miss occasionally (clock skew, retries).
    # Penalty scales with how far below the warning threshold we are.
    if tls is not None:
        tls = max(0.0, min(1.0, tls))
        if tls < 0.7:
            # Linearly attenuate: at tls=0.7 keep base, at tls=0 cap at 0.5.
            attenuation = 0.5 + 0.5 * (tls / 0.7)
            base = min(base, base * attenuation)

    # ADV branch (Sprint 7). Naive attackers respond to malformed probes
    # instead of refusing them; refusal rate < 0.7 indicates protocol
    # awareness is poor. Same soft attenuation shape as TLS.
    if adv is not None:
        adv = max(0.0, min(1.0, adv))
        if adv < 0.7:
            attenuation = 0.5 + 0.5 * (adv / 0.7)
            base = min(base, base * attenuation)

    # PRS branch (Sprint 7). PRS naturally lands lower than RKS/MVS even
    # for honest agents because perfect self-prediction is hard. Warning
    # threshold lowered to 0.4 (vs 0.7) and attenuation is gentle.
    if prs is not None:
        prs = max(0.0, min(1.0, prs))
        if prs < 0.4:
            # 0.4 → keep base, 0.0 → cap at base*0.7. Soft cap because an
            # informed attacker scores around 0.1 (random) vs honest
            # agent's 0.5+, so the gap is informative but small.
            attenuation = 0.7 + 0.3 * (prs / 0.4)
            base = min(base, base * attenuation)

    # MCS branch (Sprint 7). Mesh corroboration: when paired, an honest
    # agent's score is ~1.0 and a compromised one drops near 0.5 (the
    # uncompromised partner still publishes good co-sigs but disagree
    # on state, so verification fails on every cycle from the swap
    # onward). Cap matches RKS shape — any non-trivial failure is a
    # strong signal.
    if mcs is not None:
        mcs = max(0.0, min(1.0, mcs))
        if mcs < 0.7:
            attenuation = 0.5 + 0.5 * (mcs / 0.7)
            base = min(base, base * attenuation)

    # ZKH branch (Sprint 7). Zero-knowledge history via Merkle commit-
    # reveal. Honest framing (audit §7): in V1 ZKH coverage overlaps
    # with MVS because we persist all I/O hashes server-side. The
    # signal still adds value — failed ZKH means the agent either
    # lied about its commit root (rejected at issue time, never
    # stored) or couldn't open the Merkle path at t_star. Cap at the
    # ZKH value itself, matching the RKS shape: any non-trivial
    # failure is a strong signal.
    if zkh is not None:
        zkh = max(0.0, min(1.0, zkh))
        base = min(base, zkh) if zkh < 1.0 else base

    return float(base)


def identity_confidence_v0(
    icr: float | None,
    twc: float | None,
    ttm: float | None,
    n_events: int,
) -> float:
    """Conservative v0 score in [0, 1].

    Design (Sprint 1, intentionally conservative):
      1. **ICR gates everything.** Without observed coupling between input
         and output (ICR > 0), TWC and TTM are noise from uncalibrated β or
         finite-sample artifacts and must NOT inflate confidence. This is
         the honest reading of R4: ICR is the most robust V1 observable;
         the others reinforce it but can't stand alone.
      2. **Data-volume factor** saturates around n≈1000 events.
      3. **Signal factor** = ICR contribution + ICR-gated bonus from
         TWC/TTM. With no ICR, secondary signals are zeroed.

    Returns 0.0 when n_events == 0 or there is no ICR signal.
    """
    if n_events <= 0:
        return 0.0

    # Data-volume factor: saturates at ~63% at n=VOLUME_SATURATION_TAU,
    # ~95% at 3×TAU. Default TAU=100 means "feels established after a week
    # of normal usage" (~100 events). See docs/product/TUNABLE-PARAMETERS.md.
    volume = 1.0 - math.exp(-n_events / VOLUME_SATURATION_TAU)

    if icr is None:
        return 0.0

    icr_signal = max(0.0, min(1.0, icr))

    # Bonus only kicks in when ICR is meaningfully positive (>0.1).
    # Bonus is at most 0.5×icr_signal so secondary signals can't fully
    # dominate, but they sharpen the score when present.
    bonus = 0.0
    bonus_components: list[float] = []
    if twc is not None:
        bonus_components.append(max(0.0, min(1.0, twc / 2.0)))
    if ttm is not None:
        bonus_components.append(max(0.0, min(1.0, ttm)))
    if bonus_components and icr_signal > 0.1:
        bonus = (sum(bonus_components) / len(bonus_components)) * (icr_signal * 0.5)

    signal = min(1.0, icr_signal + bonus)
    return float(volume * signal)


# --------------------------------------------------------------------------- #
# Score explanation — customer-facing factors (Sprint 6.2)                    #
# --------------------------------------------------------------------------- #
#
# The dashboard shows Identity Confidence as a single number, but the number
# alone is opaque — a low score could mean "agent is new" (info), "watcher
# captured one-sided traffic" (action: feed it conversational data), or
# "memory probes failing" (action: investigate). `explain_score()` maps the
# internal observables to natural-language hints WITHOUT exposing the names
# ICR / TWC / TTM / MVS (those are proprietary; D-PROD.18).
#
# Each factor has:
#   severity: "good" | "info" | "warning"
#   code:     short stable identifier (for analytics/i18n later)
#   message:  human-facing copy
#
# Curation rules below are intentionally additive — multiple factors can fire
# at once. Order matters: callers should render top-down, most important first.

SCORE_FACTOR_LOW_VOLUME = "low_volume"
SCORE_FACTOR_NO_IO_COUPLING = "no_io_coupling"
SCORE_FACTOR_WEAK_IO_COUPLING = "weak_io_coupling"
SCORE_FACTOR_NEEDS_DEPTH = "needs_depth"
SCORE_FACTOR_PROBES_PENDING = "probes_pending"
SCORE_FACTOR_PROBES_FAILING = "probes_failing"
# UX-5.15.AJ — distinct from probes_failing: the agent isn't ANSWERING
# memory checks (probes expired unanswered), as opposed to answering
# them wrong. Operational, not a compromise — lands the agent in
# `caution`, not `action_required` (it's not in _ACTION_REQUIRED_CODES).
SCORE_FACTOR_PROBES_UNANSWERED = "probes_unanswered"
SCORE_FACTOR_PROBES_HEALTHY = "probes_healthy"
SCORE_FACTOR_WELL_ESTABLISHED = "well_established"
SCORE_FACTOR_SIGNATURE_FAILURES = "signature_failures"
SCORE_FACTOR_TIMING_DRIFT = "timing_drift"
SCORE_FACTOR_PROTOCOL_UNAWARE = "protocol_unaware"
SCORE_FACTOR_LOW_SELF_PREDICTION = "low_self_prediction"
SCORE_FACTOR_MESH_DISAGREEMENT = "mesh_disagreement"
SCORE_FACTOR_HISTORY_INTEGRITY = "history_integrity"
# UX-5.15.AM — the declared agent_profile doesn't match observed coupling.
# The factor dict carries an extra `suggested_profile` slug so the
# dashboard can offer a one-click fix (detect → explain → act).
SCORE_FACTOR_PROFILE_MISMATCH = "profile_mismatch"

# Sprint UX-5.12 — behavioral-layer codes. These replace the customer-facing
# emission of `no_io_coupling` / `weak_io_coupling` / `low_volume`, which
# were misleading because ICR-based factors only become trustworthy past
# BEHAVIORAL_ICR_FLOOR samples (see Exp-CvD verdict).
SCORE_FACTOR_BEHAVIORAL_CALIBRATING = "behavioral_calibrating"
SCORE_FACTOR_BEHAVIORAL_STABLE = "behavioral_stable"
SCORE_FACTOR_BEHAVIORAL_DRIFT = "behavioral_drift"


# Sprint UX-5.12 — every customer-facing factor belongs to exactly one
# trust layer. The dashboard reads this map to decide which block the
# factor belongs in. Anything missing from this dict is treated as
# internal-only and NOT emitted to the customer's trust payload.
#
# Keep this in sync with docs/product/TWO-LAYER-TRUST-DESIGN.md §4.3.
LAYER_CRYPTOGRAPHIC = "cryptographic"
LAYER_BEHAVIORAL = "behavioral"

LAYER_OF_FACTOR: dict[str, str] = {
    # Cryptographic layer — binary, immediate, MVS/RKS/ZKH/mesh-driven.
    SCORE_FACTOR_PROBES_HEALTHY: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_PROBES_PENDING: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_PROBES_FAILING: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_PROBES_UNANSWERED: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_SIGNATURE_FAILURES: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_PROTOCOL_UNAWARE: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_HISTORY_INTEGRITY: LAYER_CRYPTOGRAPHIC,
    SCORE_FACTOR_MESH_DISAGREEMENT: LAYER_CRYPTOGRAPHIC,
    # Behavioral layer — gradual, gated on sample size.
    SCORE_FACTOR_BEHAVIORAL_CALIBRATING: LAYER_BEHAVIORAL,
    SCORE_FACTOR_BEHAVIORAL_STABLE: LAYER_BEHAVIORAL,
    SCORE_FACTOR_BEHAVIORAL_DRIFT: LAYER_BEHAVIORAL,
    SCORE_FACTOR_LOW_SELF_PREDICTION: LAYER_BEHAVIORAL,
    SCORE_FACTOR_TIMING_DRIFT: LAYER_BEHAVIORAL,
    SCORE_FACTOR_PROFILE_MISMATCH: LAYER_BEHAVIORAL,
    # The four below are INTERNAL ONLY. They still get emitted by
    # explain_score for debugging/scoring, but are NOT shown to the
    # customer in the trust payload. See `is_customer_facing_factor`.
    # SCORE_FACTOR_NO_IO_COUPLING       — replaced by behavioral_calibrating
    # SCORE_FACTOR_WEAK_IO_COUPLING     — replaced by behavioral_calibrating
    # SCORE_FACTOR_LOW_VOLUME           — replaced by behavioral_calibrating
    # SCORE_FACTOR_NEEDS_DEPTH          — replaced by behavioral_calibrating
    # SCORE_FACTOR_WELL_ESTABLISHED     — replaced by behavioral_stable
}


def is_customer_facing_factor(code: str) -> bool:
    """True when the factor should appear in the customer-facing trust payload.

    Sprint UX-5.12 hides four codes that were honest at the engine level
    but misleading at the customer level: they used to say "no I/O
    coupling detected" when really they were just "we don't have enough
    samples yet". The behavioral_* codes replace them with honest copy.
    """
    return code in LAYER_OF_FACTOR


# --------------------------------------------------------------------------- #
# Factor guidance (gh-81)                                                      #
# --------------------------------------------------------------------------- #
#
# Every factor `message` says WHAT we observed. gh-81: a customer (Diana)
# reading an alert also needs to know (a) what the detection means in plain
# terms, (b) whether it's a real problem or something that clears itself with
# more events, and (c) the concrete next step. This catalog carries those
# three pieces, keyed by the stable factor `code`. It is attached to each
# customer-facing factor as `learn_more` at presentation time
# (verification_state.build_trust_block) and surfaced both in the dashboard
# (expand under each alert/score-factor row) and the developer API
# (`attention[].learn_more`).
#
# SAME jargon rules as the messages (D-PROD.18): never name ICR / TWC / TTM /
# MVS / probe_client. Talk about "memory checks", "identity checks",
# "behavior". The text must read like advice, not a stack trace.
#
# Keys are factor codes. Each value:
#   what:           plain-English description of the detection (a)
#   self_resolving: real-problem-vs-clears-on-its-own framing (b)
#   action:         the concrete next step (c)
_FACTOR_GUIDANCE: dict[str, dict[str, str]] = {
    SCORE_FACTOR_BEHAVIORAL_CALIBRATING: {
        "what": (
            "Metalins is still learning what normal looks like for this "
            "agent. Behavioral signals stay quiet until it has seen enough "
            "everyday activity to recognize the agent's pattern."
        ),
        "self_resolving": (
            "Expected for a new or low-traffic agent — not a problem. It "
            "clears on its own as more normal events accumulate."
        ),
        "action": (
            "Keep sending your agent's normal traffic. Nothing to fix."
        ),
    },
    SCORE_FACTOR_BEHAVIORAL_DRIFT: {
        "what": (
            "Recent responses stopped lining up with the inputs the way "
            "they used to — the agent's output looks decoupled from what "
            "it was asked."
        ),
        "self_resolving": (
            "A short burst of one-sided or templated traffic can cause this "
            "and recovers as varied conversation resumes. A sustained drop "
            "is worth investigating."
        ),
        "action": (
            "Confirm your agent is logging real input/output pairs (not "
            "empty or constant values). If it persists, check whether the "
            "model or system prompt behind the agent changed."
        ),
    },
    SCORE_FACTOR_PROFILE_MISMATCH: {
        "what": (
            "The agent's responses vary differently than its declared "
            "behavior setting expects."
        ),
        "self_resolving": (
            "This does not clear on its own — it reflects either a setting "
            "that never fit how the agent runs, or a genuine change in the "
            "agent (a model swap, a new prompt, or someone else operating "
            "it)."
        ),
        "action": (
            "If you expected the change, switch the behavior setting to "
            "match. If you did not, treat it as a possible compromise and "
            "investigate before changing anything."
        ),
    },
    SCORE_FACTOR_PROBES_PENDING: {
        "what": (
            "One or more memory checks are waiting for your agent to "
            "answer."
        ),
        "self_resolving": (
            "Not a problem on its own — it clears as soon as your agent "
            "answers the checks."
        ),
        "action": (
            "Make sure your agent's SDK integration is running so it can "
            "fetch and answer checks automatically."
        ),
    },
    SCORE_FACTOR_PROBES_UNANSWERED: {
        "what": (
            "Memory checks were sent to your agent and expired with no "
            "answer at all."
        ),
        "self_resolving": (
            "Usually operational rather than a compromise — the agent was "
            "offline or its integration wasn't running. It clears once the "
            "agent starts answering checks again."
        ),
        "action": (
            "Confirm the agent is online and the SDK component that fetches "
            "and answers checks is running."
        ),
    },
    SCORE_FACTOR_PROBES_FAILING: {
        "what": (
            "Your agent answered its memory checks, but the answers don't "
            "match the history Metalins has on record for it."
        ),
        "self_resolving": (
            "This does not resolve on its own — a wrong answer is a genuine "
            "red flag that the responder may not be your original agent."
        ),
        "action": (
            "Treat it as a possible compromise: check that the agent's "
            "credentials weren't leaked and that no other process is "
            "answering under its identity. If in doubt, revoke and "
            "re-register the agent."
        ),
    },
    SCORE_FACTOR_SIGNATURE_FAILURES: {
        "what": (
            "Some recent events failed their signature check — they "
            "weren't signed with this agent's key."
        ),
        "self_resolving": (
            "Legitimate activity is always at 0%, so this never clears on "
            "its own."
        ),
        "action": (
            "An unauthorized source is likely logging events under this "
            "agent's name, or its secret leaked. Rotate the secret or "
            "revoke and re-register, then check where the events are "
            "coming from."
        ),
    },
    SCORE_FACTOR_TIMING_DRIFT: {
        "what": (
            "Recent memory-check responses came back with a history "
            "position that doesn't match what Metalins expected."
        ),
        "self_resolving": (
            "A brief replication lag can cause a transient blip, but a "
            "sustained pattern doesn't clear on its own."
        ),
        "action": (
            "Check that only one instance of the agent is responding and "
            "that its view of its own history is in sync. If you run "
            "replicas, make sure they share state."
        ),
    },
    SCORE_FACTOR_PROTOCOL_UNAWARE: {
        "what": (
            "Your agent accepted deliberately malformed test challenges "
            "that a correctly-integrated agent should have refused."
        ),
        "self_resolving": (
            "An out-of-date SDK is the most common cause and it clears "
            "after upgrading; otherwise it warrants a closer look."
        ),
        "action": (
            "Update to the latest SDK. If you're already current, "
            "investigate whether something other than your agent is "
            "answering checks."
        ),
    },
    SCORE_FACTOR_LOW_SELF_PREDICTION: {
        "what": (
            "Your agent is predicting its own responses far less accurately "
            "than a healthy agent does."
        ),
        "self_resolving": (
            "This does not resolve on its own — it suggests the responder "
            "is working from observed traces rather than the agent's own "
            "internal model."
        ),
        "action": (
            "Investigate whether the agent you registered is still the one "
            "responding, and consider rotating its secret."
        ),
    },
    SCORE_FACTOR_MESH_DISAGREEMENT: {
        "what": (
            "Recent corroboration cycles with this agent's paired partner "
            "are failing."
        ),
        "self_resolving": (
            "An offline partner can cause it and it recovers when the "
            "partner returns; a persistent disagreement is worth a look."
        ),
        "action": (
            "Check that the paired agent is online and reporting. If both "
            "look healthy, investigate which side's state is wrong — a "
            "single-agent compromise is the most common cause."
        ),
    },
    SCORE_FACTOR_HISTORY_INTEGRITY: {
        "what": (
            "During recent challenges your agent couldn't prove it still "
            "holds its full past history."
        ),
        "self_resolving": (
            "This does not clear on its own — it points to a reset, a "
            "parallel copy of the agent, or a different actor without the "
            "full history."
        ),
        "action": (
            "Check whether the agent's local state was reset or replicated "
            "to another instance. If neither, treat it as a possible "
            "compromise and investigate."
        ),
    },
}


def factor_guidance(code: str | None) -> dict[str, str] | None:
    """Return the `learn_more` guidance for a factor code, or None.

    gh-81. The guidance is the customer-facing 'what does this mean / is it
    a problem / what do I do' triplet attached to a factor at presentation
    time. None for codes with no curated guidance (e.g. the positive
    `behavioral_stable` / `probes_healthy` factors, which need no advice).
    """
    if not code:
        return None
    guidance = _FACTOR_GUIDANCE.get(code)
    return dict(guidance) if guidance is not None else None


# Thresholds that decide the messaging — tuned to match the observable-level
# thresholds in identity_confidence_v0/v1 above. If you change ICR/MVS
# thresholds upstream, mirror them here.
_COUPLING_DEAD = 0.05    # below this, ICR is effectively zero → flat output trace
_COUPLING_WEAK = 0.30    # below this, signal is present but unreliable
_TWC_MIN_EVENTS = 250    # mirrors the gate in compute_trinity

# UX-5.15.AM — observed-coupling → agent-profile bands. The declared
# `agent_profile` should match how the agent actually behaves. These
# bands come from the UX-5.16 FP sweep (docs/research/CALIBRATION-RIGOR.md):
#   - functional-violation protections need coupling ≈ 1.0 (ICR ≥ ~0.95);
#     below that they false-positive heavily → a "deterministic" overclaim.
#   - subtle-drift / bulk-swap tolerate down to coupling ~0.7 (ICR ~0.59);
#     below ~0.70 the agent is clearly free-sampling → "stochastic".
_PROFILE_BAND_DETERMINISTIC_MIN = 0.95   # ICR ≥ this → behaves deterministic
_PROFILE_BAND_STOCHASTIC_MAX = 0.70      # ICR < this → behaves stochastic
# in between → low_stochastic.

# Ordered most-stochastic → most-deterministic. Used to tell whether a
# declared profile is stricter or looser than observed behavior.
_PROFILE_ORDER = ("stochastic", "low_stochastic", "deterministic")


def _observed_profile_band(icr: float | None) -> str | None:
    """Map observed input/output coupling (ICR) to the agent_profile band
    the agent actually behaves like. None when ICR isn't available yet."""
    if icr is None:
        return None
    if icr >= _PROFILE_BAND_DETERMINISTIC_MIN:
        return "deterministic"
    if icr < _PROFILE_BAND_STOCHASTIC_MAX:
        return "stochastic"
    return "low_stochastic"


def explain_score(
    *,
    icr: float | None,
    twc: float | None,
    ttm: float | None,
    mvs: float | None,
    # UX-5.15.AJ — breakdown of the MVS window so we can tell a
    # wrong-answer failure (compromise) from an all-expiry one (the
    # agent isn't answering memory checks). Default 0/0 → callers that
    # don't pass it keep the original probes_failing behavior.
    mvs_expired: int = 0,
    mvs_responded_invalid: int = 0,
    n_events: int,
    pending_probes_count: int,
    identity_confidence: float,
    has_watcher: bool = False,
    watcher_platform: str | None = None,
    has_mcp_activity: bool = False,
    # UX-5.15.AM — declared agent_profile slug ("deterministic" /
    # "low_stochastic" / "stochastic"), so the engine can flag when it
    # contradicts observed coupling. None → mismatch check skipped.
    agent_profile: str | None = None,
    # gh-80 / UX-5.15.AL / D-PROD.27 — whether this agent runs a
    # probe-capable client (SDK/daemon that fetches challenges and
    # computes proofs). When False, the round-trip mechanisms below
    # (MVS/C2, ADV/B4, PRS/B2, ZKH/C5, TLS/B3, MCS/C4) are structurally
    # absent and MUST NOT surface any factor — see the gate below.
    has_probe_client: bool = False,
    rks: float | None = None,
    tls: float | None = None,
    adv: float | None = None,
    prs: float | None = None,
    mcs: float | None = None,
    zkh: float | None = None,
) -> list[dict]:
    """Translate the internals of a snapshot into customer-facing factors.

    Returns an ordered list of `{severity, code, message}` dicts. The list
    can be empty (e.g. a perfectly healthy mature agent with nothing notable
    to flag — though we usually emit `well_established` for that case).

    NEVER mention ICR / TWC / TTM / MVS by name. Talk about behavior:
    "input/output coupling", "captured traffic", "memory checks".

    Context flags (`has_watcher`, `watcher_platform`, `has_mcp_activity`)
    let us tailor the copy to the agent's actual integration profile —
    a Telegram-watched bot, an MCP-instrumented coding agent, both, or
    neither — so the user gets actionable advice instead of generic copy.
    """
    factors: list[dict] = []

    # ----- Probe-capability gate (gh-80) ----------------------------------
    # Round-trip mechanisms — MVS/C2, ADV/B4, PRS/B2, ZKH/C5, TLS/B3,
    # MCS/C4 — only produce signal when the agent runs a probe-capable
    # client that fetches challenges and computes proofs. A V1 MCP-prompt
    # agent has none, so any score for these layers is an artifact (e.g.
    # historical probes that expired unanswered), NOT evidence of a
    # problem. The protections catalog already HIDES these mechanisms for
    # such agents (see protections_catalog._PROBE_CLIENT_MECHANISMS /
    # agent_has_probe_client); the identity engine must apply the SAME
    # gate, or it surfaces alarming copy — "Recent memory checks are
    # failing… investigate whether the right agent is being observed" —
    # for a mechanism the customer can't even see in their panel. Suppress
    # every round-trip factor at the source by clearing its inputs. Event-
    # stream layers (RKS signatures, ICR behavioral) are NOT probe-gated.
    if not has_probe_client:
        mvs = None
        pending_probes_count = 0
        adv = None
        prs = None
        mcs = None
        tls = None
        zkh = None

    # ----- Behavioral baseline gating (Sprint UX-5.12) --------------------
    # The behavioral layer makes claims only once we have enough samples
    # for the bias-corrected ICR to be trustworthy (per the Exp-CvD
    # finding: ~2,000 events). Until then we emit ONE honest factor that
    # tells the customer where they are on the curve. The old codes
    # (low_volume, no_io_coupling at low N, weak_io_coupling, needs_depth)
    # collapse into this single message — same information, no false
    # implication that the engine is making a behavioral judgment.
    if n_events < BEHAVIORAL_ICR_FLOOR:
        factors.append({
            "severity": "info",
            "code": SCORE_FACTOR_BEHAVIORAL_CALIBRATING,
            # D-PROD.18 / UX-5.15.AH — customer copy describes the
            # outcome, never the calibration parameters. We do NOT name
            # the event floor (BEHAVIORAL_ICR_FLOOR) or a "two weeks"
            # wall-clock estimate — both are calibration IP. The
            # customer's own event count is fine to show; it's their
            # data, not a system constant.
            "message": (
                f"Building behavioral baseline ({n_events:,} events so "
                "far). Behavioral signals become trustworthy once "
                "Metalins has seen enough normal usage to recognize this "
                "agent's pattern. Your agent's cryptographic identity is "
                "already in place — see the Cryptographic block above."
            ),
        })

    # ----- Behavioral drift detection (Sprint UX-5.12) --------------------
    # Only meaningful past BEHAVIORAL_ICR_FLOOR. Below that, ICR is None
    # (compute_icr refuses to fabricate a number) and we already emitted
    # `behavioral_calibrating` above. At or above the floor, Miller-Madow-
    # corrected ICR < _COUPLING_DEAD is a real signal: the agent stopped
    # responding coherently to its input. The context-aware copy (watcher
    # vs MCP) carries over from Sprint UX-5.8a — a one-sided broadcast
    # bot legitimately has weak coupling and should stay at `info`, while
    # an MCP-instrumented coding agent with zero I/O is a real warning.
    #
    # gh-84 — SDK agents (has_probe_client=True) log events through the SDK
    # API, not through an MCP conversation surface. ICR-based I/O coupling
    # maps to chat/MCP-style request→response pairs; SDK event structures
    # differ and low ICR is not evidence of drift. Emitting behavioral_drift
    # here would be a false positive. Mirror the gate used above for
    # round-trip mechanisms (has_probe_client clears MVS/ADV/etc.).
    if icr is not None and n_events >= BEHAVIORAL_ICR_FLOOR and not has_probe_client:
        if icr < _COUPLING_DEAD:
            severity = (
                "info" if (has_watcher and not has_mcp_activity) else "warning"
            )
            factors.append({
                "severity": severity,
                "code": SCORE_FACTOR_BEHAVIORAL_DRIFT,
                "message": _no_io_coupling_message(
                    has_watcher=has_watcher,
                    watcher_platform=watcher_platform,
                    has_mcp_activity=has_mcp_activity,
                ),
            })
        elif icr < _COUPLING_WEAK:
            # Soft drift — present but unreliable. Stay informational so
            # the customer isn't alarmed; the score itself already reflects
            # the weak signal.
            factors.append({
                "severity": "info",
                "code": SCORE_FACTOR_BEHAVIORAL_DRIFT,
                "message": (
                    "Behavioral pattern is weaker than typical for "
                    "established agents. Often resolves as more diverse "
                    "conversational traffic accumulates; if it persists, "
                    "check that the agent's input/output pairs are being "
                    "logged correctly."
                ),
            })

    # ----- Profile mismatch (Sprint UX-5.15.AM) ---------------------------
    # The customer declared an agent_profile; the engine now has enough
    # events to see how the agent ACTUALLY behaves. When the two disagree
    # we emit `profile_mismatch` carrying a `suggested_profile` so the
    # dashboard can offer a one-click fix.
    #   - Declared STRICTER than observed (e.g. "deterministic" but the
    #     agent free-samples) → warning: the strict-coupling protections
    #     mis-fire on legitimate model variation. The dangerous direction.
    #   - Declared LOOSER than observed (e.g. "stochastic" but the agent
    #     is reproducible) → info: the agent qualifies for stricter
    #     model-swap detection it isn't getting. An opportunity.
    # Gated on has_mcp_activity: for watcher-only agents ICR reflects a
    # one-sided broadcast, not stochasticity, so the band would mislead.
    if (
        agent_profile in _PROFILE_ORDER
        and icr is not None
        and n_events >= BEHAVIORAL_ICR_FLOOR
        and has_mcp_activity
    ):
        observed = _observed_profile_band(icr)
        if observed is not None and observed != agent_profile:
            if _PROFILE_ORDER.index(agent_profile) > _PROFILE_ORDER.index(observed):
                factors.append({
                    "severity": "warning",
                    "code": SCORE_FACTOR_PROFILE_MISMATCH,
                    # UX-5.17 #930 — this mismatch is genuinely ambiguous and
                    # the copy must NOT pre-resolve it to the benign reading.
                    # Declared-stricter-than-observed means EITHER the profile
                    # was always too strict OR the agent's behavior actually
                    # changed (model swap / takeover). Leading with "false
                    # alarms, just switch the setting" would coach a customer
                    # into silencing a real compromise signal. Present both;
                    # let them decide.
                    "message": (
                        "This agent's responses are varying more than its "
                        "declared behavior setting expects. Two very "
                        "different things cause this: the setting may have "
                        "always been too strict for how this agent really "
                        "runs (harmless — just update it), or the agent's "
                        "behavior genuinely changed — a model swap, a new "
                        "system prompt, or someone else operating it. If you "
                        "expected this change, switch the setting to match. "
                        "If you did not, treat it as a possible compromise "
                        "and investigate before changing anything."
                    ),
                    "suggested_profile": observed,
                })
            else:
                factors.append({
                    "severity": "info",
                    "code": SCORE_FACTOR_PROFILE_MISMATCH,
                    "message": (
                        "This agent behaves more consistently than its "
                        "current behavior setting. Switching the setting to "
                        "match unlocks stricter model-swap detection — more "
                        "protection, and no downside if it really runs this "
                        "way."
                    ),
                    "suggested_profile": observed,
                })

    # ----- Memory probes ---------------------------------------------------
    # Memory probes are answered by the agent via MCP. They only make
    # sense for MCP-integrated agents. For watcher-only agents (where the
    # bot is observed passively) there's no channel for the agent to
    # answer challenges — so we shouldn't pester the user about pending
    # probes there. The server-side fix is to stop issuing probes for
    # watcher-only agents in the first place; until that lands, suppress
    # the factor on the customer-facing side. See backlog: "no emit
    # memory probes for watcher-only agents".
    if mvs is None and pending_probes_count > 0:
        if has_mcp_activity:
            plural = "s" if pending_probes_count != 1 else ""
            factors.append({
                "severity": "info",
                "code": SCORE_FACTOR_PROBES_PENDING,
                "message": (
                    f"{pending_probes_count} memory check{plural} pending. "
                    "Have your agent answer them via MCP to unlock the "
                    "memory verification signal."
                ),
            })
        # else: watcher-only or unintegrated → silently skip. Memory
        # verification isn't available for that integration profile;
        # telling the user about pending probes there is just noise.
    elif mvs is not None and mvs < MVS_VETO_THRESHOLD:
        # UX-5.15.AJ — distinguish "answered wrong" from "never answered".
        # A probe answered incorrectly is a real compromise signal
        # (probes_failing → action_required, red). A probe that simply
        # EXPIRED unanswered means the agent isn't responding to memory
        # checks at all — offline, or not wired up. That's operational,
        # not a compromise: probes_unanswered → caution (amber). We only
        # downgrade when the window is ALL expiries; a single real wrong
        # answer keeps the agent at action_required. When the breakdown
        # wasn't supplied (both counts 0) we fall through to the
        # conservative probes_failing — original behavior preserved.
        if mvs_responded_invalid == 0 and mvs_expired > 0:
            plural = "s" if mvs_expired != 1 else ""
            factors.append({
                "severity": "warning",
                "code": SCORE_FACTOR_PROBES_UNANSWERED,
                "message": (
                    f"This agent isn't answering its memory checks — "
                    f"{mvs_expired} recent challenge{plural} expired with "
                    "no response. Until it answers them, its memory "
                    "can't be verified. Make sure the agent is online "
                    "and its MCP integration is running."
                ),
            })
        else:
            factors.append({
                "severity": "warning",
                "code": SCORE_FACTOR_PROBES_FAILING,
                "message": (
                    "Recent memory checks are failing — the agent's "
                    "answers don't match its known history. Investigate "
                    "whether the right agent is being observed."
                ),
            })
    elif mvs is not None and mvs >= MVS_BOOST_THRESHOLD:
        factors.append({
            "severity": "good",
            "code": SCORE_FACTOR_PROBES_HEALTHY,
            "message": "Memory checks passing consistently.",
        })

    # ----- Mesh corroboration (Sprint 7 / MCS) ----------------------------
    # When this agent has a mesh partner, both agents corroborate each
    # other's state periodically. If MCS drops, either the partner is
    # offline (no submissions) or one side has been compromised — both
    # are worth a customer-facing warning.
    if mcs is not None and mcs < 0.7:
        failure_pct = round((1.0 - mcs) * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_MESH_DISAGREEMENT,
            "message": (
                f"{failure_pct}% of recent mesh corroboration cycles with "
                "the paired agent failed. Either the partner isn't "
                "responding, or one side is reporting a state the other "
                "disagrees with. Both cases warrant a look — the most "
                "common cause is a single-agent compromise in a "
                "two-agent fleet."
            ),
        })

    # ----- Self-prediction quality (Sprint 7 / PRS) -----------------------
    # PRS catches informed attackers who observed the agent's traces but
    # don't have its internal model. Real agents land around 0.5-0.8;
    # random predictions ~0.1 at top-3 with alphabet=32.
    if prs is not None and prs < 0.4:
        hit_pct = round(prs * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_LOW_SELF_PREDICTION,
            "message": (
                f"This agent's self-predictions are hitting only "
                f"{hit_pct}% of the time. Honest agents that have access "
                "to their own response distribution land much higher; a "
                "low rate suggests the responder is guessing from "
                "observed traces rather than from an internal model. "
                "Investigate whether the agent you registered is still "
                "the one responding."
            ),
        })

    # ----- Adversarial-probe handling (Sprint 7 / ADV) --------------------
    # A protocol-aware agent recognises a deliberately malformed memory
    # check and refuses to compute a proof. A naive attacker — credentials
    # only, no SDK with structural validation — responds to everything.
    if adv is not None and adv < 0.7:
        accepted_pct = round((1.0 - adv) * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_PROTOCOL_UNAWARE,
            # D-PROD.18 / UX-5.15.AH — "AIP" framed Metalins as a
            # published open spec; it's proprietary. Say "the expected
            # request format" instead.
            "message": (
                f"This agent accepted {accepted_pct}% of malformed test "
                "challenges that a protocol-aware agent should have "
                "refused. Usually means the responder isn't validating "
                "incoming requests against the expected request format "
                "— either an out-of-date SDK or, more concerning, an "
                "actor that doesn't know the protocol."
            ),
        })

    # ----- Response timing (Sprint 7 / TLS) -------------------------------
    # Honest agents land their proof inside the derived window; agents
    # with stolen secret but no history drift outside. Below 70% we
    # surface a warning. Copy stays vague — no mention of TLS/windows.
    if tls is not None and tls < 0.7:
        missed_pct = round((1.0 - tls) * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_TIMING_DRIFT,
            "message": (
                f"{missed_pct}% of recent memory check responses arrived "
                "with a response counter that doesn't match expectations. "
                "This pattern usually means the agent's view of its own "
                "history has drifted from the server's — either a "
                "replication bug or an actor responding without the full "
                "shared history. Investigate which."
            ),
        })

    # ----- Signature integrity (Sprint 7 / RKS) ---------------------------
    # Legit signature failure rate is 0%. Any non-trivial drop is a real
    # signal: either the digest chain has been forked (attacker with
    # secret-only access) or there's a serious replication bug. We never
    # name "RKS" or "signature" beyond user-readable terms.
    _RKS_WARNING = 0.95
    if rks is not None and rks < _RKS_WARNING:
        invalid_pct = round((1.0 - rks) * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_SIGNATURE_FAILURES,
            "message": (
                f"{invalid_pct}% of recent events failed signature "
                "verification. Legitimate activity should be at 0%. This "
                "almost always means an unauthorized source is logging "
                "events under this agent's name, or the agent's secret "
                "has been compromised. Investigate immediately."
            ),
        })

    # ----- History integrity (Sprint 7 / ZKH) -----------------------------
    # ZKH is the most "audit-y" of the layers: the agent commits to a
    # Merkle root over its full local history-digest chain and then
    # opens a randomly-chosen leaf. A drop here means EITHER the agent
    # has been refusing to commit (or committing wrong roots), OR it
    # can't open the path at challenge time — both correlate with an
    # actor that doesn't actually hold the full history. Hard threshold
    # at 0.9: legitimate agents should be at 100%.
    _ZKH_WARNING = 0.9
    if zkh is not None and zkh < _ZKH_WARNING:
        failed_pct = round((1.0 - zkh) * 100)
        factors.append({
            "severity": "warning",
            "code": SCORE_FACTOR_HISTORY_INTEGRITY,
            "message": (
                f"{failed_pct}% of recent history-integrity challenges "
                "failed. This usually means the agent can't reconstruct "
                "its own past — either because the local state was reset, "
                "replicated to a parallel instance, or a different actor "
                "is responding without the full history. Investigate which."
            ),
        })

    # ----- Positive behavioral summary (Sprint UX-5.12) -------------------
    # `behavioral_stable` is the design doc §2.3 success state. We emit
    # it when the engine has enough data AND has not flagged a drift.
    # Unlike the old `well_established`, this does NOT require an empty
    # factors list — cryptographic factors like `probes_healthy` are
    # orthogonal and shouldn't suppress the behavioral all-clear.
    has_behavioral_drift = any(
        (f or {}).get("code") == SCORE_FACTOR_BEHAVIORAL_DRIFT for f in factors
    )
    has_behavioral_calibrating = any(
        (f or {}).get("code") == SCORE_FACTOR_BEHAVIORAL_CALIBRATING
        for f in factors
    )
    if (
        n_events >= BEHAVIORAL_ICR_STABLE
        and icr is not None
        and icr >= _COUPLING_WEAK
        and not has_behavioral_drift
        and not has_behavioral_calibrating
    ):
        factors.append({
            "severity": "good",
            "code": SCORE_FACTOR_BEHAVIORAL_STABLE,
            "message": (
                "Behavioral baseline stable across the observed window. "
                "We've seen enough usage to recognize this agent's normal "
                "pattern."
            ),
        })

    return factors


def _no_io_coupling_message(
    *,
    has_watcher: bool,
    watcher_platform: str | None,
    has_mcp_activity: bool,
) -> str:
    """Build the most specific 'no input/output coupling' copy we can.

    V1 model (D-PROD.18): one agent = one identity = one integration
    surface. Watcher and MCP are mutually exclusive per agent; mixing
    them would conflate two different identities into one observation
    window. The cases below reflect that — we don't tell a watcher-only
    user to "also connect MCP" because that would break the model.

    Decision:
      - watcher only → platform-specific one-sided-traffic copy
      - MCP only    → empty/constant input or output in logged events
      - neither     → no integration yet (events somehow exist anyway —
                      a data integrity edge case worth flagging)
    """
    if has_watcher and not has_mcp_activity:
        platform = (watcher_platform or "").lower()
        platform_label = {
            "telegram": "Telegram bot",
            "discord": "Discord bot",
            "slack": "Slack bot",
            "x": "X bot",
        }.get(platform, "watched bot")
        return (
            "No input→output pairs detected in the captured activity. "
            f"This is normal for one-sided traffic — for example, a "
            f"{platform_label} whose messages get no replies, or a channel "
            "the bot only broadcasts to. The score will stay low until "
            "real conversational pairs (incoming messages followed by the "
            "bot's responses) start flowing."
        )
    if has_mcp_activity and not has_watcher:
        return (
            "No input→output pairs detected in the MCP-logged activity. "
            "Most likely cause: the agent is logging events with an empty "
            "input or output field, or always producing the same output. "
            "Make sure each logged event has a meaningful, non-empty input "
            "and a corresponding output that depends on it."
        )
    return (
        "No input→output pairs detected yet. Connect this agent via a "
        "watcher (for public bots) or via MCP (for SDK-instrumented "
        "agents) so we can observe real activity. The score will stay "
        "low until the integration surface emits request→response pairs."
    )
