"""Behavioral feature schema — server-side contract for #63.

The SDK (``metalins/behavioral.py``) computes a bag of low-resolution,
hard-to-invert structural features client-side and ships them as
``metadata['behavioral']`` on every ``log_event``. The server stores the
whole metadata blob in ``EventLog.metadata_json`` and the κ-engine V2
(``app.kappa.engine``) reads ``behavioral`` back out to baseline agents
and detect drift.

This module is the single source of truth for that schema on the server:

  * ``validate_behavioral`` checks the types of a submitted blob and
    returns a normalized copy. It is *lenient by design* — events
    without a ``behavioral`` key (every event logged before #63) stay
    perfectly valid; only a present-but-malformed blob is rejected.
  * The κ-engine imports ``CONTINUOUS_FEATURES`` / ``DISCRETE_FEATURES``
    / ``ERROR_CLASSES`` so the feature vocabulary never drifts between
    the validator and the statistics.

Keeping the vocabulary here (not duplicated in the engine) means adding a
feature is a one-file change.
"""
from __future__ import annotations

from typing import Any

# Must match metalins.behavioral.ERROR_CLASSES in the SDK.
ERROR_CLASSES = (
    "none",
    "timeout",
    "refusal",
    "retry",
    "tool_error",
    "parse_error",
)

# Continuous numeric features — the engine runs distributional tests
# (KS / Wasserstein) over these.
CONTINUOUS_FEATURES = (
    "output_length_chars",
    "output_length_tokens",
    "input_length_chars",
    "sentence_count_output",
    "mean_sentence_length_output",
    "latency_ms",
)

# Boolean format markers — frequency / chi-squared on these.
BOOL_FEATURES = (
    "had_code_block",
    "had_list",
    "had_markdown",
)

# Categorical / structured features handled specially by the engine.
DISCRETE_FEATURES = ("error_class",)

# The full set of feature names the SDK emits. Used for SDK↔server
# vocabulary lockstep tests and as the allow-list anchor.
ALL_FEATURE_NAMES = (
    *CONTINUOUS_FEATURES,
    *BOOL_FEATURES,
    *DISCRETE_FEATURES,
    "tool_calls",
    "format_markers",
    "token_bag_lsh",
)

# Hard bounds on attacker-controlled fields. The blob is persisted
# verbatim into EventLog.metadata_json (and rolled into
# AgentBaseline.features_json) and fed to per-event statistics, so an
# unbounded field is a storage-exhaustion + CPU-amplification vector.
LSH_HEX_LEN = 16            # 64-bit SimHash → exactly 16 hex chars (or "")
MAX_TOOL_CALLS = 64         # tool names per event
MAX_TOOL_NAME_LEN = 128
MAX_FORMAT_MARKERS = 32
MAX_UNKNOWN_KEYS = 16       # forward-compat headroom, still bounded
MAX_STRING_LEN = 256        # any stray string value


class BehavioralSchemaError(ValueError):
    """Raised when a present ``behavioral`` blob has the wrong shape."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BehavioralSchemaError(message)


def _as_non_negative_number(value: Any, field: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"behavioral.{field} must be a number, got {type(value).__name__}",
    )
    _require(value >= 0, f"behavioral.{field} must be >= 0")
    return value


def validate_behavioral(behavioral: Any) -> dict[str, Any]:
    """Validate + normalize a ``metadata['behavioral']`` blob.

    Returns a normalized copy: unknown ``error_class`` values are coerced
    to ``"none"``, ``tool_calls`` entries are stringified, and numeric
    fields are passed through after type/range checks. Raises
    ``BehavioralSchemaError`` (a ``ValueError``) on a hard type mismatch
    so the API layer can turn it into a 400.

    Unknown extra keys are preserved untouched — forward-compat for
    features a newer SDK adds before the server learns about them.
    """
    _require(
        isinstance(behavioral, dict),
        f"behavioral must be an object, got {type(behavioral).__name__}",
    )

    out = dict(behavioral)

    for field in CONTINUOUS_FEATURES:
        if field not in behavioral:
            continue
        value = behavioral[field]
        if field == "latency_ms" and value is None:
            continue  # latency is optional / may be unmeasured
        out[field] = _as_non_negative_number(value, field)

    for field in BOOL_FEATURES:
        if field in behavioral:
            _require(
                isinstance(behavioral[field], bool),
                f"behavioral.{field} must be a bool",
            )

    if "tool_calls" in behavioral:
        tc = behavioral["tool_calls"]
        _require(
            isinstance(tc, list),
            "behavioral.tool_calls must be a list of tool names",
        )
        _require(
            len(tc) <= MAX_TOOL_CALLS,
            f"behavioral.tool_calls exceeds {MAX_TOOL_CALLS} entries",
        )
        names = [str(t) for t in tc]
        for n in names:
            _require(
                len(n) <= MAX_TOOL_NAME_LEN,
                f"behavioral.tool_calls entry exceeds {MAX_TOOL_NAME_LEN} chars",
            )
        out["tool_calls"] = names

    if "error_class" in behavioral:
        ec = behavioral["error_class"]
        _require(
            isinstance(ec, str),
            "behavioral.error_class must be a string",
        )
        out["error_class"] = ec if ec in ERROR_CLASSES else "none"

    if "format_markers" in behavioral:
        fm = behavioral["format_markers"]
        _require(
            isinstance(fm, dict),
            "behavioral.format_markers must be an object",
        )
        _require(
            len(fm) <= MAX_FORMAT_MARKERS,
            f"behavioral.format_markers exceeds {MAX_FORMAT_MARKERS} keys",
        )
        for k, v in fm.items():
            _require(
                isinstance(v, bool),
                f"behavioral.format_markers.{k} must be a bool",
            )

    if "token_bag_lsh" in behavioral:
        lsh = behavioral["token_bag_lsh"]
        _require(
            isinstance(lsh, str),
            "behavioral.token_bag_lsh must be a hex string",
        )
        _require(
            len(lsh) <= LSH_HEX_LEN,
            f"behavioral.token_bag_lsh exceeds {LSH_HEX_LEN} hex chars",
        )
        if lsh:
            try:
                int(lsh, 16)
            except ValueError as exc:
                raise BehavioralSchemaError(
                    "behavioral.token_bag_lsh must be hexadecimal"
                ) from exc

    # Bound unknown/forward-compat keys: cap their count and reject
    # oversized string values so a client can't smuggle unbounded data
    # into the persisted blob under a novel key.
    unknown_keys = [k for k in behavioral if k not in ALL_FEATURE_NAMES]
    _require(
        len(unknown_keys) <= MAX_UNKNOWN_KEYS,
        f"behavioral carries more than {MAX_UNKNOWN_KEYS} unknown keys",
    )
    for k in unknown_keys:
        v = behavioral[k]
        if isinstance(v, str):
            _require(
                len(v) <= MAX_STRING_LEN,
                f"behavioral.{k} string exceeds {MAX_STRING_LEN} chars",
            )

    return out
