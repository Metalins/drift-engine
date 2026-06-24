/**
 * Agent profile — how variable the agent's outputs are for the same input.
 *
 * Sprint UX-5.15.L (2026-05-19). Jose's feedback: the previous flow
 * silently defaulted every agent to `deterministic`, which made sense for
 * the Sprint UX-5.16 calibration sweep (Claude Code @ temp 0) but is the
 * wrong default for the personal-use majority (Andrea running ChatGPT
 * Desktop, Claude Desktop, role-play apps — all non-deterministic).
 *
 * The profile selects WHICH protections from `protections_catalog.py`
 * apply to this agent. A wrong profile gives one of two bad outcomes:
 *
 *   - Marked deterministic but actually stochastic → the deterministic-
 *     only protections (B1.functional_violation_*) misfire on legitimate
 *     model noise. False positives.
 *
 *   - Marked stochastic but actually deterministic → the system stops
 *     trying the strict-coupling checks and an attacker swapping the
 *     model with a different LLM goes undetected longer. False negatives.
 *
 * So we ASK at agent creation. No default. The customer is the only one
 * who knows the answer.
 *
 * The backend slugs are `deterministic` / `low_stochastic` / `stochastic`,
 * stored as `metadata.agent_profile`. They live in
 * `server/app/services/protections_catalog.py`. The customer-facing labels
 * here translate them into plain English — internal terms never reach
 * the UI.
 */

// The 3 slugs below are internal API enum values matching the backend
// (see server/app/services/protections_catalog.py). They never reach
// customer-facing copy — the customer sees `AGENT_PROFILE_OPTIONS[*].label`
// instead. The `metalins:internal-allowed` tag exempts these strings
// from the CI bundle guard.
export type AgentProfile = "deterministic" | "low_stochastic" | "stochastic"; // metalins:internal-allowed

const VALID: ReadonlySet<string> = new Set([
  "deterministic", // metalins:internal-allowed
  "low_stochastic", // metalins:internal-allowed
  "stochastic", // metalins:internal-allowed
]);

/**
 * Read `metadata.agent_profile` and return it as a typed value. Returns
 * `null` for legacy agents created before this field existed — those
 * stay on whatever default the backend assigns at register time. The
 * caller (AgentSettings) surfaces a "Set this now" hint when null.
 */
export function readAgentProfile(
  metadata: Record<string, unknown> | null | undefined,
): AgentProfile | null {
  const raw = metadata?.agent_profile ?? metadata?.profile;
  if (typeof raw === "string" && VALID.has(raw)) {
    return raw as AgentProfile;
  }
  return null;
}

/**
 * Human-readable options for the radio in /agents/new and the <select>
 * in AgentSettings. Order: the most common case first.
 *
 *   1. low_stochastic — Claude Code / Cursor / Claude Desktop with
 *      default settings. Mostly the same answer, occasional variation.
 *      This is the "I don't know exactly" sensible middle.
 *   2. stochastic — chat-heavy creative use. Free-form sampling at
 *      temperature >0.5. The honest default for the majority of Andrea
 *      use cases (Claude.ai chat, ChatGPT chat, role-play assistants).
 *   3. deterministic — opinionated low-temp setups (Claude Code at
 *      temp=0, scripted bots, code generation). Unlocks the strictest
 *      detection but only if you actually run this way.
 */
// The three `value` strings are internal API slugs — they're never
// rendered to the customer (the `label` is). The `metalins:internal-allowed`
// tag exempts these lines from the CI bundle guard.
export const AGENT_PROFILE_OPTIONS: ReadonlyArray<{
  value: AgentProfile;
  label: string;
  helper: string;
}> = [
  {
    value: "stochastic", // metalins:internal-allowed
    label: "Free-form chat",
    helper:
      "Claude Desktop, Claude.ai, ChatGPT, role-play agents. The same question gets very different wording each time — that's by design. Pick this for any general-purpose chat assistant.",
  },
  {
    value: "low_stochastic", // metalins:internal-allowed
    label: "Mostly consistent",
    helper:
      "Coding agents like Claude Code or Cursor with default settings. Same prompt usually gets the same answer, with small variations. Pick this for code assistants and structured agents.",
  },
  {
    value: "deterministic", // metalins:internal-allowed
    label: "Strict / reproducible",
    helper:
      "Scripted bots or code generation at temperature 0 — same prompt gives the exact same response, every time. Turns on the strictest checks — pick it only if your agent truly runs this way, or normal variation will get flagged.",
  },
];

/**
 * Short label for inline display in lists / cards.
 */
export function shortLabel(profile: AgentProfile | null): string {
  switch (profile) {
    case "deterministic": // metalins:internal-allowed
      return "Strict / reproducible";
    case "low_stochastic": // metalins:internal-allowed
      return "Mostly consistent";
    case "stochastic": // metalins:internal-allowed
      return "Creative or chat-style";
    case null:
      return "Not set";
  }
}
