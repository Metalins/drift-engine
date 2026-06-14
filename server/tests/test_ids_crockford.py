"""Tests for the Crockford-base32 ID generator (Sprint R2.S2).

Verifies:
  • Output uses ONLY the Crockford alphabet (no I, L, O, U).
  • Output is uppercase.
  • Prefix is preserved verbatim.
  • Suffix length is stable across many calls.
  • No collisions across a 50_000-sample run (sanity check on entropy).
"""
from __future__ import annotations

from app.core.ids import new_id


CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
# Letters explicitly excluded by Crockford base32 — must NEVER appear
# in a generated suffix.
FORBIDDEN = set("ILOUilou")


def test_new_id_uses_only_crockford_alphabet():
    for _ in range(2000):
        out = new_id("agt")
        assert out.startswith("agt_")
        suffix = out[len("agt_"):]
        # No forbidden ambiguous chars.
        assert not (set(suffix) & FORBIDDEN), (
            f"suffix {suffix!r} contains a forbidden char from {FORBIDDEN}"
        )
        # Every char in alphabet.
        assert set(suffix).issubset(CROCKFORD), (
            f"suffix {suffix!r} has chars outside Crockford alphabet"
        )


def test_new_id_suffix_is_stable_length():
    """16 random bytes → 26 Crockford chars (ceil(128/5))."""
    for _ in range(500):
        out = new_id("prf")
        suffix = out[len("prf_"):]
        assert len(suffix) == 26, (
            f"suffix length {len(suffix)} != 26 for {out!r}"
        )


def test_new_id_preserves_prefix():
    for prefix in ("agt", "prf", "anc", "key", "cust", "wat"):
        out = new_id(prefix)
        assert out.startswith(prefix + "_"), (
            f"expected prefix {prefix}_ on {out!r}"
        )


def test_new_id_no_collisions_50k():
    """Sanity check that 16 bytes of entropy give us collision-free
    output at the scale we'll see in V1. Real production crypto is
    overdetermined here; this guard exists to catch a regression to
    a fixed/degenerate generator."""
    seen = set()
    for _ in range(50_000):
        out = new_id("agt")
        assert out not in seen, f"collision: {out!r}"
        seen.add(out)
    assert len(seen) == 50_000
