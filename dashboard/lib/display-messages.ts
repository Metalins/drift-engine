/**
 * display-messages — UX presentation layer for engine status codes (#31).
 *
 * The engine speaks in internal codes: behavioral/cryptographic states
 * ("not_enough_data", "caution", "action_required"), score-factor codes
 * ("challenges_expired", "memory_check_failed", "mcp_not_responding", …)
 * and raw watcher states ("pending" / "error" / "paused"). Those names are
 * correct *inside* the engine, but they must NEVER reach a customer's
 * screen as raw jargon.
 *
 * This module is the single frontend dictionary that turns an engine code
 * into human copy. The engine is untouched (#31: "NO modificar el
 * backend/engine — solo la capa de presentación"). Only the dashboard
 * decides what the human reads.
 *
 * Two guarantees:
 *   1. Closed code spaces (the CryptographicState / BehavioralState /
 *      watcher unions) are typed `Record<Union, …>`, so adding a new engine
 *      state without giving it human copy fails `npm run typecheck`.
 *   2. Open code spaces (score-factor / "attention" codes, which the engine
 *      can grow at will) get an explicit map PLUS humanizeCode() as the
 *      last-resort fallback — an unrecognized code degrades to
 *      "Challenges expired", never the raw "challenges_expired".
 */
import type { BehavioralState, CryptographicState, WatcherSummary } from "./api";

type WatcherState = WatcherSummary["state"];

/**
 * snake_case / kebab-case engine code → "Sentence case" prose. The
 * last-resort safety net: even a code we have never seen before is shown as
 * readable words instead of a raw identifier with underscores.
 */
export function humanizeCode(code: string): string {
  const cleaned = code.replace(/[_-]+/g, " ").trim().replace(/\s+/g, " ");
  if (!cleaned) return "";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/**
 * Cryptographic-identity state → short human label (badges, strips).
 * Exhaustive: the compiler enforces a label for every state.
 */
export const CRYPTO_STATUS_DISPLAY: Record<CryptographicState, string> = {
  verified: "Verified",
  unverified: "Setting up",
  caution: "Verify with care",
  action_required: "Not trusted",
  revoked: "Revoked",
};

/**
 * Behavioral-baseline state → short human label. "Building a baseline"
 * covers both the pre-floor (`not_enough_data`) and accumulating
 * (`building`) phases; callers that want a percentage append it themselves.
 */
export const BEHAVIORAL_STATUS_DISPLAY: Record<BehavioralState, string> = {
  not_enough_data: "Learning your baseline",
  building: "Building a baseline",
  stable: "Consistent",
  drift_detected: "Something changed",
};

/**
 * Watcher (bot connection) state → human label. Replaces the raw
 * "PENDING" / "ERROR" / "PAUSED" the badge used to print. "Needs attention"
 * matches the wording the dashboard list already uses for a degraded agent.
 */
export const WATCHER_STATE_DISPLAY: Record<WatcherState, string> = {
  active: "Connected",
  pending: "Connecting",
  error: "Needs attention",
  paused: "Paused",
};

/**
 * Score-factor / "attention" codes → a customer-facing sentence. These are
 * the codes the issue calls out explicitly. The backend normally ships a
 * sanitized `message` for each factor (see identity_engine.explain_score),
 * so this map is the fallback used when a message is missing — and the
 * guarantee that, if one ever arrives raw, the user still reads English.
 *
 * Open-ended on purpose: the engine may add codes faster than this map. Any
 * code not listed falls through to humanizeCode().
 */
export const ATTENTION_DISPLAY: Record<string, string> = {
  challenges_expired:
    "Your agent hasn't answered its latest checks. Make sure the process is still running.",
  memory_check_failed:
    "We couldn't confirm your agent's memory. Check that it's online and reachable.",
  mcp_not_responding:
    "The integration looks disconnected. Try restarting your agent.",
  probes_unanswered:
    "Your agent stopped answering its identity checks. Confirm it's still running.",
  protocol_unaware:
    "Your agent isn't responding to identity checks the way we expect.",
  profile_mismatch:
    "Recent activity doesn't match the profile set for this agent.",
};

/**
 * Resolve a score-factor / attention code to human copy.
 *
 * @param code     the engine code (e.g. "challenges_expired").
 * @param message  the backend's already-sanitized message, if present. A
 *                 non-empty message always wins — the backend owns the most
 *                 specific phrasing; this dictionary only fills the gaps.
 */
export function displayAttention(code: string, message?: string | null): string {
  const trimmed = message?.trim();
  if (trimmed) return trimmed;
  return ATTENTION_DISPLAY[code] ?? humanizeCode(code);
}

/** Human label for a cryptographic state (never the raw code). */
export function displayCryptoStatus(state: CryptographicState): string {
  return CRYPTO_STATUS_DISPLAY[state] ?? humanizeCode(state);
}

/** Human label for a behavioral state (never the raw code). */
export function displayBehavioralStatus(state: BehavioralState): string {
  return BEHAVIORAL_STATUS_DISPLAY[state] ?? humanizeCode(state);
}

/** Human label for a watcher state (never the raw "pending"/"error"). */
export function displayWatcherState(state: WatcherState): string {
  return WATCHER_STATE_DISPLAY[state] ?? humanizeCode(state);
}
