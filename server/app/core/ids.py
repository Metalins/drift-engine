"""ID generation for entities.

Sprint UX-5.11 R2 / R2.S2 (2026-05-18). Switched from
`secrets.token_urlsafe` (base64url alphabet = `[A-Za-z0-9_-]`) to
Crockford base32 (32 unambiguous symbols, no I/L/O/U). Rationale:

  • `token_urlsafe` produces strings that mix letter O and digit 0,
    letter l/I/i and digit 1. Real example caught in Sofía v3 synthetic
    run: `agt_SOu91jW3TWkEKXwvNOOO7A` (five letter-Os, zero digits) —
    when a human glances at this in a URL or copies it by eye, the
    misreading rate is high. Same applies to `prf_*` proof IDs that
    appear in shareable verify links.
  • Crockford base32 was designed for this exact use case: skip the
    confusable letters (I, L, O, U), use uppercase letters + digits,
    case-insensitive on input (we always emit uppercase).
  • Existing IDs in the database stay valid forever — we only change
    NEW ID generation. Lookup is byte-equal so legacy ids continue to
    resolve.

Entropy: 16 random bytes ≈ 128 bits. With Crockford-base32 we encode 5
bits per character, so we emit ~26 chars after the prefix. Collision
probability at 1 billion ids is ~2^-68, well under "never happens in
practice".
"""
import secrets


# Crockford base32 alphabet — 32 unambiguous characters.
# Drops: I (confused with 1), L (confused with 1), O (confused with 0),
# U (reserved for accidental obscenities). Reference:
# https://www.crockford.com/base32.html
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _crockford_encode(b: bytes) -> str:
    """Encode bytes as a Crockford-base32 string, MSB-first, no padding.

    We bit-pack the bytes into a single integer and read 5-bit chunks
    off the top. For 16 input bytes (128 bits) we emit ceil(128/5) = 26
    characters. The leading character may carry fewer bits than 5 — we
    use the low bits, so an all-zero input produces all "0" characters,
    which is fine for ID purposes.
    """
    n = int.from_bytes(b, byteorder="big")
    bits = len(b) * 8
    n_chars = (bits + 4) // 5  # ceil
    out = []
    for i in range(n_chars - 1, -1, -1):
        chunk = (n >> (i * 5)) & 0b11111
        out.append(_CROCKFORD_ALPHABET[chunk])
    return "".join(out)


def new_id(prefix: str) -> str:
    """Generate a prefixed ID like 'agt_8K3J2N5R7H1Q9C4M0V6X2T8Y4W'.

    Always uppercase Crockford-base32 after the prefix. 16 random bytes
    of entropy → 26 chars suffix. Total length: len(prefix) + 1 + 26.
    """
    return f"{prefix}_{_crockford_encode(secrets.token_bytes(16))}"
