/**
 * Typed API client for the Drift Engine server.
 *
 * Self-hosting pivot (gh-119): the bearer token is the server-minted session
 * JWT read from the httpOnly `ml_session` cookie (see lib/auth/server.ts).
 * Falls back to NEXT_PUBLIC_METALINS_API_KEY only if explicitly configured —
 * useful for testing without a login flow.
 *
 * All public functions are async server-side (Server Component fetches). The
 * base URL is a server-only env var (DRIFT_ENGINE_API_URL → the `server`
 * service in docker-compose), never NEXT_PUBLIC, since these run server-side.
 */
import { getAccessToken, serverApiUrl } from "@/lib/auth/server";

const API_URL = serverApiUrl();

/** Legacy static-key fallback. Empty in normal Sprint 3a-auth operation. */
const STATIC_API_KEY = process.env.NEXT_PUBLIC_METALINS_API_KEY || "";

// --------------------------------------------------------------------------- //
// Types                                                                       //
// --------------------------------------------------------------------------- //

export interface AgentSummary {
  agent_id: string;
  /**
   * Sprint UX-5.7a (#634) — human-readable slug for the public verify
   * URL. Optional on older API responses; treat as fallback to
   * agent_id when present.
   */
  public_slug?: string | null;
  name: string;
  model: string | null;
  framework: string | null;
  is_active: boolean;
  created_at: string | null;
  revoked_at?: string | null;
  last_event_at: string | null;
  event_count: number;
  /**
   * Sprint UX-5.12 — two-layer trust block. The list endpoint returns
   * the same shape as the public `trust` block on `/v1/public/agents/...`
   * so dashboard rows can render the compact strip "● verified · ◐
   * baseline 16%" without an extra round-trip. Older deploys that
   * haven't rolled out yet omit the field — the row falls back to a
   * conservative "unverified" rendering. Independent of
   * `latest_confidence` which was dropped in this sprint.
   */
  trust?: TrustBlock;
  /**
   * Sprint 6.5 — integration surface for the row. Dashboard list uses
   * this to decide which quick-action buttons to show. Defaults to
   * "none" if the server didn't include it (older API / not redeployed).
   */
  integration_surface?: "watcher" | "mcp" | "sdk" | "none";
  /**
   * Sprint UX-5.9-D — watcher state for the row, so the dashboard list
   * can show "Connection issue" when an adapter has been failing
   * without an extra round-trip per row. One of "pending" | "active" |
   * "error" | "paused", or null if there is no watcher.
   */
  watcher_state?: "pending" | "active" | "error" | "paused" | null;
  /**
   * Sprint UX-5.15.C2 — compact protections rollup for the dashboard list.
   * Counts only (no per-item details); the full catalog with descriptions
   * lives in the agent detail response under `protections`.
   */
  protections_summary?: {
    active_count: number;
    applicable_count: number;
    total_count: number;
    agent_profile: "deterministic" | "low_stochastic" | "stochastic"; // metalins:internal-allowed — internal API enum value, not rendered as customer copy // metalins:internal-allowed — internal API enum value, not rendered as customer copy
  };
  /**
   * Sprint UX-5.15.A — customer-facing tier (T0..T4). Server-derived from
   * the agent's event count (verification_state.derive_tier). Optional on
   * older API responses that haven't redeployed — TierBadge renders
   * nothing when it's absent.
   */
  tier?: TierInfo;
  /**
   * Sprint UX-5.15.AL — whether the agent runs a probe-capable client.
   * False for every V1 MCP-prompt agent. The dashboard hides the
   * memory-probe panels (Recent checks / Pending) when this is false,
   * since a non-probe-capable agent never has probe activity to show.
   */
  probe_capable?: boolean;
}

/**
 * Sprint UX-5.15.A — tier ladder rung. A tier is a convenience label for
 * which protections are active at a given event count (D-PROD.24); the
 * contract is the protection catalog, not this number.
 */
export interface TierInfo {
  tier: "T0" | "T1" | "T2" | "T3" | "T4";
  name: string;
  next_tier: "T1" | "T2" | "T3" | "T4" | null;
  next_tier_name: string | null;
  events_observed: number;
  events_to_next: number | null;
}

/**
 * Customer-facing explanation factor for the Identity Confidence score.
 * Sprint 6.2 — the server returns these alongside the snapshot so the
 * dashboard can tell the user WHY the score is what it is, in plain
 * English, without revealing the internal observables (ICR / TWC / TTM /
 * MVS — see D-PROD.18).
 */
export type ScoreFactorSeverity = "good" | "info" | "warning";

/**
 * gh-81 — the "learn more" triplet attached to a factor. The `message`
 * says WHAT we observed; this says what it means, whether it's a real
 * problem or self-resolving, and the concrete next step. Surfaced as an
 * expand under each alert/score-factor row. The backend
 * (identity_engine.factor_guidance) is the single source of this copy.
 */
export interface FactorGuidance {
  /** What the detection means, in plain terms. */
  what: string;
  /** Whether it's a real problem or clears itself with more events. */
  self_resolving: string;
  /** The suggested next step. */
  action: string;
}

export interface ScoreFactor {
  severity: ScoreFactorSeverity;
  code: string;
  message: string;
  /**
   * Sprint UX-5.15.AM — present only on the `profile_mismatch` factor.
   * The agent_profile slug the engine suggests, fed to the one-click
   * action in ProfileMismatchAlert.
   */
  suggested_profile?: string;
  /**
   * gh-81 — per-factor context for the dashboard expand. Present on
   * factors with curated guidance (most warnings + the calibrating /
   * pending info factors); absent on positive factors that need no advice.
   */
  learn_more?: FactorGuidance;
}

/**
 * Sprint UX-5.12 — two-layer trust model. Replaces the single-number
 * `identity_confidence` + the single-string `verification_state` with
 * two independent layers per `docs/product/TWO-LAYER-TRUST-DESIGN.md`.
 *
 * Layer 1 — Cryptographic identity. Binary, immediate. Driven by MVS /
 * RKS / ZKH probes and signature checks. Available from event #1. Never
 * susceptible to finite-sample bias because it's not statistical.
 *
 * Layer 2 — Behavioral baseline. Gradual, sample-size aware. Driven by
 * ICR / TWC / TTM with bias correction + floor. Honest about needing
 * data — refuses to make claims below `events_floor` events.
 *
 * The two layers DO NOT compose into a single score. The dashboard shows
 * them side-by-side. Customer copy never exposes the internal observable
 * names; only the `factors[].message` strings are shown.
 */
export type CryptographicState =
  | "verified"
  | "unverified"
  | "caution"
  | "action_required"
  | "revoked";

export type BehavioralState =
  | "not_enough_data"
  | "building"
  | "stable"
  | "drift_detected";

export interface CryptographicLayer {
  state: CryptographicState;
  /** First moment we believed in the agent. Null when unverified/revoked. */
  since: string | null;
  /** Timestamp of the most recent observable. Null when no probes yet. */
  last_probe_at: string | null;
  factors: ScoreFactor[];
}

export interface BehavioralLayer {
  state: BehavioralState;
  /** Events the engine has actually observed for this agent. */
  events_observed: number;
  /** Minimum N before ICR is reported (matches `BEHAVIORAL_ICR_FLOOR`). */
  events_floor: number;
  /** N above which the layer is considered stable (`BEHAVIORAL_ICR_STABLE`). */
  events_stable: number;
  /** Plain-English descriptor for the verify card. "consistent" |
   * "drifting" | null while still building. */
  descriptor: "consistent" | "drifting" | null;
  factors: ScoreFactor[];
}

export interface TrustBlock {
  cryptographic: CryptographicLayer;
  behavioral: BehavioralLayer;
}

/**
 * Per-window snapshot of an agent's identity state.
 * Sprint UX-5.12 drop: removed `identity_confidence` (the single-number
 * field that was vulnerable to finite-sample bias). The score factors are
 * still emitted so the snapshot timeline can show what changed window to
 * window, but the headline trust shape is now `trust` on the parent agent
 * payload. See TWO-LAYER-TRUST-DESIGN.md §5.
 */
export interface ObservableSnapshot {
  ts: string | null;
  window_start: string | null;
  window_end: string | null;
  n_events: number;
  score_factors: ScoreFactor[];
}

/**
 * Sprint 6.3 — integration surface. V1 model (D-PROD.18): one agent =
 * one identity = one integration surface. Used by the agent-detail
 * header to show the right CTAs (Manage bot vs Manage MCP vs both
 * onboarding paths side-by-side when nothing is connected yet).
 */
export type IntegrationSurface = "none" | "watcher" | "mcp" | "sdk";

export interface IntegrationWatcher {
  id: string;
  platform: string;
  state: string;
  display_name: string | null;
}

export interface Integration {
  surface: IntegrationSurface;
  watcher: IntegrationWatcher | null;
  /**
   * ISO timestamp when the user explicitly disconnected MCP for this
   * agent. Null while MCP is accepting events. Sprint 6.4 / #575.
   */
  mcp_disabled_at: string | null;
}

/**
 * One row in the protections checklist (Sprint UX-5.15.C).
 *
 * IP boundary: the dashboard NEVER sees internal mechanism names
 * (B1.bulk_swap, ICR, MVS, etc.). The backend exposes only opaque slugs
 * (proof_NN) + sanitized customer copy.
 */
export interface ProtectionItem {
  id: string;              // opaque slug, e.g. "proof_07"
  name: string;            // short customer-facing label
  description: string;     // longer description shown on expand
  caveat: string | null;   // honest limitation if any
  // gh-79 — honest inline note when this protection is in the catalog but
  // not on the agent's activation path for its detected behavior mode
  // (e.g. a deterministic-only check on a stochastic agent). null otherwise.
  behavior_note: string | null;
  active: boolean;
  events_to_activation: number | null;
  applicable: boolean;
  // gh-79 — whether this protection's detection actually fires for the
  // agent's detected behavior mode. false → shown with behavior_note,
  // covered by an equivalent variant instead. May be absent on older
  // cached payloads; treat missing as true.
  applies_to_behavior?: boolean;
  tier: "T0" | "T1" | "T2" | "T3";
}

export interface ProtectionsBlock {
  agent_profile: "deterministic" | "low_stochastic" | "stochastic"; // metalins:internal-allowed — internal API enum value, not rendered as customer copy
  items: ProtectionItem[];
  summary: {
    active_count: number;
    applicable_count: number;
    total_count: number;
  };
}

export interface AgentDetail extends AgentSummary {
  metadata: Record<string, unknown>;
  revocation_reason: string | null;
  pending_probes_count: number;
  latest_observables: ObservableSnapshot | null;
  integration: Integration;
  /**
   * Sprint UX-5.12 — same two-layer block exposed publicly. Authenticated
   * detail view always includes it (no `?` here vs. the optional one on
   * `AgentSummary`).
   */
  trust: TrustBlock;
  /**
   * Sprint UX-5.15.A — protections catalog checklist (20 items per the
   * server-side catalog). Source: docs/research/PROTECTIONS-CATALOG.md.
   */
  protections?: ProtectionsBlock;
}

export interface ListAgentsResponse {
  agents: AgentSummary[];
  count: number;
  limit: number;
  offset: number;
}

export interface ObservablesHistoryResponse {
  agent_id: string;
  is_active: boolean;
  latest: ObservableSnapshot | null;
  history: ObservableSnapshot[];
  count: number;
}

export interface ProbeRow {
  probe_id: string;
  target_event_count: number;
  nonce: string;
  status?: string;
  valid?: boolean | null;
  issued_at: string | null;
  responded_at?: string | null;
  expires_at: string | null;
}

export interface ProbesResponse {
  agent_id: string;
  status: string;
  probes: ProbeRow[];
}

// --------------------------------------------------------------------------- //
// Errors                                                                      //
// --------------------------------------------------------------------------- //

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// --------------------------------------------------------------------------- //
// Internal fetch wrapper                                                      //
// --------------------------------------------------------------------------- //

/**
 * API1b Step 2 (UX-5.17 — docs/product/PUBLIC-API-DESIGN.md §8).
 *
 * The dashboard BFF endpoints moved off the bare `/v1/` namespace to
 * `/internal/v1/` so `/v1/` can become the public developer API. The
 * server dual-mounts both paths during the migration window, so this
 * rewrite is safe to ship before the server drops the bare mount.
 *
 * Only the BFF calls move. The relying-party plane stays on `/v1/`:
 * `/v1/public/*` and `/v1/verify-proof` are NOT dual-mounted and must
 * keep their original paths.
 */
function internalize(path: string): string {
  if (path.startsWith("/v1/public/") || path === "/v1/verify-proof") {
    return path; // public relying-party plane — stays on /v1/
  }
  if (path.startsWith("/v1/")) {
    return "/internal" + path;
  }
  return path;
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  // Prefer the Supabase session JWT; fall back to a static API key only if
  // the user explicitly set one (useful for SDK-style scripts).
  const jwt = await getAccessToken();
  const token = jwt ?? STATIC_API_KEY;
  if (!token) {
    throw new ApiError(
      401,
      "Not authenticated — sign in via magic link at /login",
    );
  }
  const res = await fetch(`${API_URL}${internalize(path)}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    // Server data is fresh-by-default during alpha — no caching layer yet.
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // Fall through to statusText.
    }
    throw new ApiError(res.status, detail);
  }
  // 204 No Content or otherwise empty body — don't try to parse JSON.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

// --------------------------------------------------------------------------- //
// Unauthenticated fetch — for public endpoints (verify page, JWKS, etc.)      //
// --------------------------------------------------------------------------- //

async function publicFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // Fall through to statusText.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/**
 * Public agent info — Sprint UX-5.5f (#629) + Sprint UX-5.7a (#634).
 * Powers the `/verify/<agent_id>` and `/v/<slug>` pages. Callable
 * without auth. Returns only the fields a stranger needs to make a
 * trust decision.
 */
/**
 * Sprint UX-5.9-F/G — public anchor on the verify card. Each anchor links
 * the agent to an external identity (Telegram bot username, GitHub user,
 * DNS-controlled domain, etc.) that the visitor can independently
 * sanity-check. `verified_at` is when the anchor was last validated.
 */
export interface PublicAnchor {
  type: "telegram" | "github" | "dns" | string;
  value: string;
  verified_at: string | null;
  method: string;
}

export interface PublicAgentInfo {
  agent_id: string;
  public_slug: string | null;
  name: string;
  is_active: boolean;
  verified_since: string | null;
  last_active: string | null;
  revoked_at: string | null;
  /**
   * Sprint UX-5.12 — two-layer trust block. Replaces the single
   * `verification_state` + `baselining_threshold` pair we used until
   * UX-5.9. Optional on older server deploys; the verify card falls
   * back to a conservative "unverified" rendering when missing so we
   * never accidentally show a "verified" badge to a third party.
   */
  trust?: TrustBlock;
  event_count?: number;
  external_anchors?: PublicAnchor[];
  /**
   * Sprint UX-5.11 R2 / bug-visitor-1 — primary seller-identity anchor.
   * Derived server-side as the first verified anchor in priority order
   * (telegram > github > dns). When present, the verify page uses it
   * as the "Operated by ..." headline. Null when the customer hasn't
   * verified any anchor; in that case the page shows the agent name
   * only and the visitor falls back to trusting Metalins or asking
   * the seller for an anchor.
   */
  primary_anchor?: PublicAnchor | null;
  /**
   * Sprint UX-5.11 R2 / R2.6 (2026-05-18) — how this agent is plumbed.
   * "mcp"     → reachable via MCP/HTTP; the agent itself can emit
   *             proofs on demand. CTA on the verify page reads "ask
   *             the agent for a verified link".
   * "watcher" → Telegram bot watcher. CTA reads "ask the operator
   *             to generate a proof from their dashboard".
   * "none"    → not yet connected. Generic CTA.
   * Optional on older deploys (falls back to "none").
   */
  integration_surface?: "watcher" | "mcp" | "sdk" | "none";
}

export async function getPublicAgent(
  agentId: string,
): Promise<PublicAgentInfo> {
  return publicFetch<PublicAgentInfo>(
    `/v1/public/agents/${encodeURIComponent(agentId)}`,
  );
}

/**
 * Lookup the same payload via the human-readable slug. Sprint UX-5.7a
 * (#634). Used by the `/v/<slug>` route that Carlos pastes in his
 * bot's bio.
 */
export async function getPublicAgentBySlug(
  slug: string,
): Promise<PublicAgentInfo> {
  return publicFetch<PublicAgentInfo>(
    `/v1/public/agents/by-slug/${encodeURIComponent(slug)}`,
  );
}

// --------------------------------------------------------------------------- //
// Public API                                                                  //
// --------------------------------------------------------------------------- //

export async function listAgents(opts?: {
  limit?: number;
  offset?: number;
  includeRevoked?: boolean;
}): Promise<ListAgentsResponse> {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts?.includeRevoked) params.set("include_revoked", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ListAgentsResponse>(`/v1/agents${qs}`);
}

export async function getAgent(agentId: string): Promise<AgentDetail> {
  return apiFetch<AgentDetail>(`/v1/agents/${encodeURIComponent(agentId)}`);
}

/**
 * Sprint UX-5.15.UX1 — lightweight endpoint dedicated to the protections
 * checklist. Used by the dashboard's auto-refresh poll so it doesn't
 * re-fetch the entire agent detail every 30 seconds.
 *
 * Returns the same shape as `AgentDetail.protections` (server-side: see
 * `protections_catalog.py`) plus a `last_updated_at` ISO timestamp the
 * UI shows as "Updated 47s ago".
 */
export interface ProtectionsLiveResponse {
  agent_id: string;
  event_count: number;
  agent_profile: "deterministic" | "low_stochastic" | "stochastic"; // metalins:internal-allowed — internal API enum value, not rendered as customer copy
  integration_surface: "watcher" | "mcp" | "sdk" | "none";
  items: import("./api").ProtectionItem[];
  summary: {
    active_count: number;
    applicable_count: number;
    total_count: number;
  };
}

export async function getAgentProtections(
  agentId: string,
): Promise<ProtectionsLiveResponse> {
  return apiFetch<ProtectionsLiveResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/protections`,
  );
}

export async function getObservables(
  agentId: string,
  opts?: { limit?: number; recompute?: boolean }
): Promise<ObservablesHistoryResponse> {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.recompute) params.set("recompute", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ObservablesHistoryResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/observables${qs}`
  );
}

export async function getProbes(
  agentId: string,
  opts?: { status?: "pending" | "responded" | "expired" | "all"; limit?: number }
): Promise<ProbesResponse> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ProbesResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/probes${qs}`
  );
}

// --------------------------------------------------------------------------- //
// Sprint 3a-auth additions: /v1/me + API keys CRUD + agent registration       //
// --------------------------------------------------------------------------- //

export interface CustomerProfile {
  customer_id: string;
  email: string;
  auth_type: "api_key" | "jwt";
  api_key_id: string | null;
  api_key_name: string | null;
}

export async function getMe(): Promise<CustomerProfile> {
  return apiFetch<CustomerProfile>("/v1/me");
}

// --------------------------------------------------------------------------- //
// Email preferences — Sprint UX-5.13.E.5 (2026-05-18)                         //
// --------------------------------------------------------------------------- //
//
// Wraps /v1/me/email-preferences. Returns synthetic defaults with
// `is_default: true` when no row exists, so the UI can render
// placeholders rather than empty state. PATCH only sends the fields
// the user actually touched.

export interface EmailPreferences {
  alert_email: string | null;
  /** Address we would send to NOW — alert_email if set, else auth email. */
  effective_email: string;
  alerts_enabled: boolean;
  threshold_crossed_enabled: boolean;
  drift_detected_enabled: boolean;
  weekly_digest_enabled: boolean;
  is_default: boolean;
}

export async function getEmailPreferences(): Promise<EmailPreferences> {
  return apiFetch<EmailPreferences>("/v1/me/email-preferences");
}

export async function updateEmailPreferences(
  body: Partial<{
    alert_email: string | null;
    alerts_enabled: boolean;
    threshold_crossed_enabled: boolean;
    drift_detected_enabled: boolean;
    weekly_digest_enabled: boolean;
  }>,
): Promise<EmailPreferences> {
  return apiFetch<EmailPreferences>("/v1/me/email-preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Permanently delete the calling customer's account — every agent and
 * all of its data, the account-level rows, the customer record. Free
 * tier: immediate. `reason` is mandatory (the server rejects a blank
 * one). The only thing kept is an audit row (email + when + reason).
 */
export async function deleteAccount(
  reason: string,
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/v1/me/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export interface ApiKeySummary {
  id: string;
  name: string | null;
  description: string | null;
  agent_id: string | null;
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKeySummary {
  secret: string;
  warning: string;
}

export interface ListAgentKeysResponse {
  agent_id: string;
  keys: ApiKeySummary[];
  count: number;
}

/**
 * Sprint UX-5.11 / bug-andrea-3 (2026-05-17) — customer-level key
 * summary. Extends ApiKeySummary with explicit `scope` and (when the
 * key is bound to an agent) the agent's display name, so the global
 * /keys page can render "andrea-laptop · scoped to
 * andrea-claude-code-laptop" without an extra round-trip.
 */
export interface CustomerKeySummary extends ApiKeySummary {
  scope: "customer-wide" | "agent-scoped";
  agent_name: string | null;
}

export interface CustomerKeyCreated extends CustomerKeySummary {
  secret: string;
  warning: string;
}

export interface ListCustomerKeysResponse {
  customer_id: string;
  keys: CustomerKeySummary[];
  count: number;
}

export async function listAgentKeys(
  agentId: string,
  opts?: { includeRevoked?: boolean },
): Promise<ListAgentKeysResponse> {
  const params = new URLSearchParams();
  if (opts?.includeRevoked) params.set("include_revoked", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ListAgentKeysResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/api-keys${qs}`,
  );
}

export async function createAgentKey(
  agentId: string,
  body: { name: string; description?: string },
): Promise<ApiKeyCreated> {
  return apiFetch<ApiKeyCreated>(
    `/v1/agents/${encodeURIComponent(agentId)}/api-keys`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function revokeApiKey(keyId: string): Promise<{
  id: string;
  is_active: boolean;
  revoked_at: string;
}> {
  return apiFetch(`/v1/api-keys/${encodeURIComponent(keyId)}/revoke`, {
    method: "POST",
  });
}

/**
 * List all keys for the authenticated customer (customer-wide +
 * agent-scoped). Sprint UX-5.11 / bug-andrea-3.
 */
export async function listCustomerKeys(
  opts?: { includeRevoked?: boolean },
): Promise<ListCustomerKeysResponse> {
  const params = new URLSearchParams();
  if (opts?.includeRevoked) params.set("include_revoked", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<ListCustomerKeysResponse>(
    `/v1/customers/me/api-keys${qs}`,
  );
}

/** Create a customer-wide API key. Sprint UX-5.11 / bug-andrea-3. */
export async function createCustomerKey(body: {
  name: string;
  description?: string;
}): Promise<CustomerKeyCreated> {
  return apiFetch<CustomerKeyCreated>("/v1/customers/me/api-keys", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface RegisterAgentRequestBody {
  name: string;
  model?: string;
  framework?: string;
  metadata?: Record<string, unknown>;
  behavior_samples?: unknown[];
}

export interface RegisterAgentResult {
  agent_id: string;
  created_at: string;
  // UX-5.17 #931 — the agent's secret, shown once. Needed only to
  // connect via the SDK / HTTP API (MCP and bot watchers don't use it).
  agent_secret: string;
}

export async function registerAgent(
  body: RegisterAgentRequestBody,
): Promise<RegisterAgentResult> {
  return apiFetch<RegisterAgentResult>("/v1/agents/register", {
    method: "POST",
    body: JSON.stringify({
      ...body,
      // Server expects these defaults for the metadata + samples fields.
      metadata: body.metadata ?? {},
      behavior_samples: body.behavior_samples ?? [],
    }),
  });
}


// --------------------------------------------------------------------------- //
// Update / revoke agent (Sprint 4.11)                                         //
// --------------------------------------------------------------------------- //

export interface UpdateAgentBody {
  name?: string;
  model?: string;
  framework?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdatedAgent {
  agent_id: string;
  name: string;
  model: string | null;
  framework: string | null;
  metadata: Record<string, unknown>;
  is_active: boolean;
}

export async function updateAgent(
  agentId: string,
  body: UpdateAgentBody,
): Promise<UpdatedAgent> {
  return apiFetch<UpdatedAgent>(
    `/v1/agents/${encodeURIComponent(agentId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(body),
    },
  );
}

export async function revokeAgent(
  agentId: string,
  reason?: string,
): Promise<{ agent_id: string; revoked_at: string }> {
  return apiFetch<{ agent_id: string; revoked_at: string }>(
    `/v1/agents/revoke`,
    {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, reason }),
    },
  );
}

/**
 * Sprint 6.4 / #575 — MCP disconnect / reconnect.
 *
 * Disconnect stops the server from accepting events on this agent's MCP
 * surface (POST /v1/log_event returns 403 until reconnected). Watcher
 * disconnect uses the existing DELETE /v1/watchers/{id} (soft-delete).
 */
export interface DisconnectMcpResult {
  agent_id: string;
  mcp_disabled_at: string;
}

export async function disconnectMcp(
  agentId: string,
  confirmationName: string,
): Promise<DisconnectMcpResult> {
  return apiFetch<DisconnectMcpResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/disconnect-mcp`,
    {
      method: "POST",
      body: JSON.stringify({ confirmation_name: confirmationName }),
    },
  );
}

export interface ReconnectMcpResult {
  agent_id: string;
  mcp_reconnected_at: string;
}

export async function reconnectMcp(
  agentId: string,
): Promise<ReconnectMcpResult> {
  return apiFetch<ReconnectMcpResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/reconnect-mcp`,
    { method: "POST" },
  );
}

/**
 * UX-5.15.P / D-PROD.25 — Reset behavior baseline.
 *
 * The customer accepts the new behavior as the new normal. Pre-reset
 * events stay archived (auditable evidence) — the identity engine
 * ignores observables prior to the reset when computing the current
 * shape. The behavioral state machine re-enters not_enough_data ->
 * building -> stable cleanly.
 *
 * Requires JWT auth (dashboard owner only). The LLM / MCP client
 * cannot trigger this — that's the moat.
 */
export interface ResetBaselineResult {
  agent_id: string;
  last_baseline_reset_at: string;
  baseline_reset_count: number;
}

export async function resetBaseline(
  agentId: string,
  confirmationName: string,
): Promise<ResetBaselineResult> {
  return apiFetch<ResetBaselineResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/reset-baseline`,
    {
      method: "POST",
      body: JSON.stringify({ confirmation_name: confirmationName }),
    },
  );
}

/**
 * UX-5.17 #505 / #931 — Re-issue an agent's secret.
 *
 * A full re-key: the agent gets a brand-new `agent_secret` and its
 * cryptographic verification restarts from a fresh genesis. The hash
 * chain is rooted in the secret, so a new secret unavoidably means a
 * new chain — past verification history is cleared and the tier
 * resets. The agent keeps its id / name / slug / keys / anchors /
 * connected bots; only its verification history is wiped.
 *
 * Same confirm-by-name guard as revoke / reset-baseline. JWT auth only
 * (dashboard owner) — the LLM / MCP client cannot trigger this.
 *
 * The returned `agent_secret` is shown once and never retrievable
 * again.
 */
export interface ReissueSecretResult {
  agent_id: string;
  agent_secret: string;
  reissued_at: string;
  secret_warning: string;
}

export async function reissueSecret(
  agentId: string,
  confirmationName: string,
): Promise<ReissueSecretResult> {
  return apiFetch<ReissueSecretResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/reissue-secret`,
    {
      method: "POST",
      body: JSON.stringify({ confirmation_name: confirmationName }),
    },
  );
}

// ---------- Sprint 6-A2A 6.1 — issue verifiable identity claim --------

/** Allowed TTLs in seconds. Matches the server-side _ALLOWED_TTL_SECONDS. */
export const ISSUE_PROOF_TTLS = [
  { seconds: 300, label: "5 minutes" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 86400, label: "24 hours" },
] as const;

export interface IssueProofResult {
  proof_id: string;
  agent_id: string;
  kappa_proof: string;
  issued_at: string;
  expires_at: string;
  scope: string | null;
  score: number | null;
}

export async function issueProof(
  agentId: string,
  opts: { ttl_seconds: number; scope?: string },
): Promise<IssueProofResult> {
  return apiFetch<IssueProofResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/issue-proof`,
    {
      method: "POST",
      body: JSON.stringify({
        ttl_seconds: opts.ttl_seconds,
        scope: opts.scope ?? null,
      }),
    },
  );
}

// ---------- Sprint 6-A2A 6.2 — verifications served (timeline) --------

export interface VerificationAttempt {
  id: string;
  proof_id: string | null;
  verified_at: string | null;
  valid: boolean;
  reason: string | null;
  scope: string | null;
}

export interface VerificationsResponse {
  agent_id: string;
  total: number;
  valid: number;
  items: VerificationAttempt[];
}

export async function getVerifications(
  agentId: string,
  opts?: { limit?: number },
): Promise<VerificationsResponse> {
  const qs =
    opts?.limit !== undefined ? `?limit=${encodeURIComponent(opts.limit)}` : "";
  return apiFetch<VerificationsResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/verifications${qs}`,
  );
}

export interface RecomputeResult {
  agent_id: string;
  ts: string | null;
  n_events: number;
  /**
   * Sprint UX-5.12 — the recompute endpoint now emits the same two-layer
   * trust block the detail endpoint returns, so the dashboard can refresh
   * the visual state without a second round-trip. Replaces the legacy
   * `identity_confidence` single number.
   */
  trust: TrustBlock;
  score_factors: ScoreFactor[];
  next_recompute_at: string;
}

/**
 * Trigger an on-demand Identity Confidence recompute for one agent.
 * Sprint 6 (2026-05-16) — fixes the "no data for 60 min after first activity"
 * onboarding gap. Server enforces a 60-second cooldown; if too soon, the API
 * returns 429 and `ApiError` surfaces the `Retry-After` header content in
 * `.message`. Returns 412 if there are no events yet to compute over.
 */
export async function recomputeAgent(agentId: string): Promise<RecomputeResult> {
  return apiFetch<RecomputeResult>(
    `/v1/agents/${encodeURIComponent(agentId)}/recompute`,
    { method: "POST" },
  );
}


// --------------------------------------------------------------------------- //
// Watchers (Sprint 4)                                                         //
// --------------------------------------------------------------------------- //

export type WatcherPlatform = "telegram" | "discord" | "slack" | "x";

export interface WatcherSummary {
  id: string;
  agent_id: string;
  platform: WatcherPlatform;
  display_name: string | null;
  state: "pending" | "active" | "error" | "paused";
  error_message: string | null;
  polling_interval_sec: number;
  last_polled_at: string | null;
  events_logged: number;
  created_at: string;
  paused_at: string | null;
}

export interface WatcherListResponse {
  watchers: WatcherSummary[];
  supported_platforms: string[];
}

export interface CreateWatcherBody {
  platform: WatcherPlatform;
  token: string;
  display_name?: string;
}

export async function listWatchers(agentId: string): Promise<WatcherListResponse> {
  return apiFetch<WatcherListResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/watchers`,
  );
}

export async function createWatcher(
  agentId: string,
  body: CreateWatcherBody,
): Promise<{ watcher: WatcherSummary }> {
  return apiFetch<{ watcher: WatcherSummary }>(
    `/v1/agents/${encodeURIComponent(agentId)}/watchers`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function pauseWatcher(watcherId: string): Promise<WatcherSummary> {
  return apiFetch<WatcherSummary>(
    `/v1/watchers/${encodeURIComponent(watcherId)}/pause`,
    { method: "POST" },
  );
}

/**
 * Sprint UX-5.10-8 — force an immediate poll when a watcher is stuck
 * in error state. Used by the "Retry now" button in WatcherManager.
 */
export async function retryWatcher(watcherId: string): Promise<WatcherSummary> {
  return apiFetch<WatcherSummary>(
    `/v1/watchers/${encodeURIComponent(watcherId)}/retry`,
    { method: "POST" },
  );
}

export async function resumeWatcher(watcherId: string): Promise<WatcherSummary> {
  return apiFetch<WatcherSummary>(
    `/v1/watchers/${encodeURIComponent(watcherId)}/resume`,
    { method: "POST" },
  );
}

export async function deleteWatcher(watcherId: string): Promise<void> {
  await apiFetch<void>(`/v1/watchers/${encodeURIComponent(watcherId)}`, {
    method: "DELETE",
  });
}

// --------------------------------------------------------------------------- //
// External anchors — Sprint UX-5.9-G                                          //
// --------------------------------------------------------------------------- //

export interface AnchorRow {
  id: string;
  type: string;
  method: string;
  value: string | null;
  verified_at: string | null;
  created_at: string | null;
  last_check_at: string | null;
}

export interface StartGithubAnchorResponse {
  anchor_id: string;
  challenge_token: string;
  instructions: string;
}

export async function listAnchors(
  agentId: string,
): Promise<{ anchors: AnchorRow[] }> {
  return apiFetch<{ anchors: AnchorRow[] }>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors`,
  );
}

export async function startGithubAnchor(
  agentId: string,
): Promise<StartGithubAnchorResponse> {
  return apiFetch<StartGithubAnchorResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors/github/start`,
    { method: "POST" },
  );
}

export async function verifyGithubAnchor(
  agentId: string,
  body: { anchor_id: string; gist_url: string },
): Promise<AnchorRow> {
  return apiFetch<AnchorRow>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors/github/verify`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function deleteAnchor(
  agentId: string,
  anchorId: string,
): Promise<void> {
  await apiFetch<void>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors/${encodeURIComponent(anchorId)}`,
    { method: "DELETE" },
  );
}

// --------------------------------------------------------------------------- //
// Telegram anchor — Sprint UX-5.11 R2 / bug-r1-carlos-1 (2026-05-18)          //
// --------------------------------------------------------------------------- //

export interface StartTelegramAnchorResponse {
  anchor_id: string;
  challenge_token: string;
  instructions: string;
}

export async function startTelegramAnchor(
  agentId: string,
): Promise<StartTelegramAnchorResponse> {
  return apiFetch<StartTelegramAnchorResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors/telegram/start`,
    { method: "POST" },
  );
}

export async function verifyTelegramAnchor(
  agentId: string,
  body: { anchor_id: string; telegram_username: string },
): Promise<AnchorRow> {
  return apiFetch<AnchorRow>(
    `/v1/agents/${encodeURIComponent(agentId)}/anchors/telegram/verify`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

// --------------------------------------------------------------------------- //
// Claim slug from verified anchor — Sprint UX-5.11 R2 / R2.3b (2026-05-18)    //
// --------------------------------------------------------------------------- //

export interface ClaimSlugResponse {
  slug: string;
  previous_slug: string | null;
}

export async function claimSlugFromAnchor(
  agentId: string,
  anchorId: string,
): Promise<ClaimSlugResponse> {
  return apiFetch<ClaimSlugResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/claim-slug`,
    {
      method: "POST",
      body: JSON.stringify({ anchor_id: anchorId }),
    },
  );
}

// --------------------------------------------------------------------------- //
// Verify a κ-Proof JWT — Sprint UX-5.11 R2 / R2.4 (2026-05-18)                //
// --------------------------------------------------------------------------- //

export interface VerifyProofResult {
  valid: boolean;
  agent_id?: string | null;
  public_slug?: string | null;
  agent_name?: string | null;
  proof_id?: string | null;
  issued_at?: string | null;
  expires_at?: string | null;
  still_active?: boolean | null;
  scope?: string | null;
  score?: number | null;
  steps?: number | null;
  reason?: string | null;
}

/**
 * Verify a κ-Proof JWT via the public, unauth endpoint. Called by the
 * verify page when the visitor lands on `/v/<slug>?proof=<jwt>` so the
 * page can render the proof's reference (scope) + freshness instead of
 * the static-link view.
 *
 * This is intentionally unauthenticated — anyone with a JWT should be
 * able to check it. `apiFetch` falls back to no Authorization header
 * if there's no Supabase session, so it works fine for public visitors.
 */
export async function verifyProof(
  kappaProof: string,
): Promise<VerifyProofResult> {
  return apiFetch<VerifyProofResult>(`/v1/verify-proof`, {
    method: "POST",
    body: JSON.stringify({ kappa_proof: kappaProof }),
  });
}

/**
 * Sprint UX-5.11 R2 / R2.7 (2026-05-18) — resolve a short `proof_id`
 * into the full JWT. Used by the verify page when the URL carries the
 * compact `?p=<proof_id>` form. The full JWT then goes through the
 * regular `verifyProof` flow.
 *
 * Returns null if the proof_id is unknown (server 404). Throws on
 * other errors so the caller can render a "verifier unreachable"
 * banner.
 */
export interface ProofLookupResult {
  proof_id: string;
  agent_id: string;
  kappa_proof: string;
  issued_at: string | null;
  expires_at: string | null;
  scope: string | null;
}

export async function lookupProofById(
  proofId: string,
): Promise<ProofLookupResult | null> {
  try {
    return await apiFetch<ProofLookupResult>(
      `/v1/public/proofs/${encodeURIComponent(proofId)}`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

// --------------------------------------------------------------------------- //
// Webhook endpoints — Sprint UX-5.10-6                                        //
// --------------------------------------------------------------------------- //

export interface WebhookRow {
  id: string;
  url: string;
  is_active: boolean;
  last_delivery_at: string | null;
  last_delivery_status: number | null;
  last_delivery_error: string | null;
  created_at: string | null;
}

export interface CreateWebhookResponse {
  webhook: WebhookRow;
  secret: string;
}

export async function listWebhooks(
  agentId: string,
): Promise<{ webhooks: WebhookRow[] }> {
  return apiFetch<{ webhooks: WebhookRow[] }>(
    `/v1/agents/${encodeURIComponent(agentId)}/webhooks`,
  );
}

export async function createWebhook(
  agentId: string,
  url: string,
): Promise<CreateWebhookResponse> {
  return apiFetch<CreateWebhookResponse>(
    `/v1/agents/${encodeURIComponent(agentId)}/webhooks`,
    { method: "POST", body: JSON.stringify({ url }) },
  );
}

export async function deleteWebhook(
  agentId: string,
  webhookId: string,
): Promise<void> {
  await apiFetch<void>(
    `/v1/agents/${encodeURIComponent(agentId)}/webhooks/${encodeURIComponent(webhookId)}`,
    { method: "DELETE" },
  );
}
