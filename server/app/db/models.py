"""DB models for Metalins core entities."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, Boolean, ForeignKey, Float, Index
from sqlalchemy.orm import relationship

from app.db.session import Base


class Customer(Base):
    """Customer account — a human/org that owns API keys + agents.

    Created on first login via Supabase Auth (Sprint 3b). `id` matches
    Supabase's `auth.users.id` so we can validate JWTs against it without
    pegar a Supabase server-side. Sprint 3a does not use this table yet —
    forward-compat for Sprint 3b customer auth layer (D-PROD.13 + D-PROD.14).
    """
    __tablename__ = "customers"

    id = Column(String, primary_key=True)            # = auth.users.id (UUID stored as str)
    email = Column(String, nullable=False, unique=True, index=True)
    plan = Column(String, nullable=False, default="free")   # 'free' | 'growth' | 'scale' (D-PROD.14)
    stripe_customer_id = Column(String, nullable=True)      # Filled when Paddle/Lemon entra Sprint 4
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    # gh-117/gh-118 (self-hosted local auth, 2026-06-19). Drift Engine no
    # longer leans on Supabase for login. The admin account lives here with a
    # bcrypt `password_hash`; `is_admin` marks the bootstrap account; and
    # `must_change_password` is set when the account is created with the
    # default password so the dashboard can force a change on first login.
    # All three are nullable / defaulted so existing customer rows (created
    # under the old Supabase flow) remain valid without a backfill.
    password_hash = Column(String, nullable=True)
    is_admin = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    must_change_password = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class APIKey(Base):
    """Customer API key for SDK auth.

    Sprint 3a-auth: keys can now be scoped to a specific agent. A key with
    `agent_id` set can only see that one agent; a key with `agent_id=NULL` is
    customer-wide (used by the bootstrap admin key and legacy keys). Customers
    create new keys from the dashboard via `POST /v1/agents/{id}/api-keys`,
    which always returns the raw key once and stores only the hash.
    """
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)
    # FK to Customer. Nullable on legacy keys created before Sprint 3a-auth.
    # New keys created via the dashboard always set customer_id from the JWT.
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True, index=True)
    # Optional scope: if set, this key may only operate on that specific agent.
    # Legacy / admin keys leave this NULL → customer-wide visibility.
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True, index=True)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    owner_email = Column(String, nullable=False, index=True)
    label = Column(String, nullable=True)
    # User-facing name (e.g. "production", "ci-bot") shown in the dashboard list.
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class Agent(Base):
    """Registered AI agent."""
    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    api_key_id = Column(String, ForeignKey("api_keys.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    model = Column(String, nullable=True)
    framework = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    baseline_kappa = Column(JSON, nullable=True)  # κ-fingerprint baseline (cifrado en prod)
    enrolment_score = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(String, nullable=True)

    # Sprint 6.4 / #575 — MCP integration disconnect. NULL = MCP surface
    # accepting events. Non-NULL = the user explicitly disconnected MCP;
    # log_event returns 403 until reconnected. Watcher disconnect uses the
    # existing soft-delete on the Watcher row.
    mcp_disabled_at = Column(DateTime, nullable=True)

    # gh-77 — server-DETECTED behavior mode. The customer no longer declares
    # an `agent_profile`/`behavior_mode` at registration (that was a leaky
    # abstraction — see gh-77). The engine observes the agent's first events
    # and decides whether it behaves deterministically (same input → same
    # output) or stochastically (samples freely). Values:
    #   "unknown"        — not enough evidence yet (default at registration)
    #   "deterministic"  — reproducible outputs for repeated inputs
    #   "stochastic"     — outputs vary for repeated inputs
    # Drives which protections apply via resolve_agent_profile(); see
    # app.services.behavior_detection and app.services.protections_catalog.
    detected_behavior_mode = Column(
        String, nullable=False, default="unknown", server_default="unknown"
    )

    # Sprint UX-5.7a (#634) — human-readable slug for the public verify
    # URL. Lowercase, [a-z0-9-]+, globally unique. Auto-generated from the
    # watcher display name (e.g. "@SenalesCryptoCarlos" → "senales-crypto-
    # carlos") or from the agent name as fallback. Lets Carlos paste
    # `verify.metalins.ai/v/senales-crypto-carlos` in his Telegram bio
    # instead of the unfit `/verify/agt_<hex>` link.
    public_slug = Column(String, unique=True, index=True, nullable=True)

    verifies = relationship("Verification", back_populates="agent")


class Verification(Base):
    """A single verify event with its κ-Proof."""
    __tablename__ = "verifications"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    proof_jwt = Column(String, nullable=False)  # the κ-Proof itself (JWT signed)
    score = Column(Float, nullable=False)
    verified = Column(Boolean, nullable=False)
    steps = Column(Integer, default=1)  # 1 = standard, N = multi-step
    scope = Column(String, nullable=True)  # optional scope for issued tokens
    issued_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=False)

    agent = relationship("Agent", back_populates="verifies")


class Revocation(Base):
    """Revoked κ-Proofs (CRL)."""
    __tablename__ = "revocations"

    proof_id = Column(String, primary_key=True)
    agent_id = Column(String, nullable=False, index=True)
    revoked_at = Column(DateTime, default=datetime.utcnow, index=True)
    reason = Column(String, nullable=True)


Index("idx_verifications_issued", Verification.agent_id, Verification.issued_at)


class VerificationAttempt(Base):
    """Append-only timeline of /v1/verify-proof calls (Sprint 6-A2A 6.2).

    Distinct from `verifications` (which records mints/issuances): this
    table logs every CONSUMPTION of a proof — a relying party hitting
    the public endpoint. Drives the dashboard's "Recent verifications"
    panel for issuers, and the social-proof counter on /verify/<token>.

    Privacy decision (Jose, CHECKPOINT 2026-05-16): we do NOT store
    the relying party's IP. Only timestamp + outcome + scope snapshot.
    The agent_id is what links rows back to a customer's dashboard.
    """
    __tablename__ = "verification_attempts"

    id = Column(String, primary_key=True)
    proof_id = Column(String, nullable=True, index=True)  # null if decode failed
    agent_id = Column(String, nullable=True, index=True)  # null if no sub claim
    verified_at = Column(DateTime, default=datetime.utcnow, index=True)
    valid = Column(Boolean, nullable=False)
    reason = Column(String, nullable=True)  # e.g. "signature_invalid", "revoked"
    scope = Column(String, nullable=True)  # snapshot of the JWT scope claim


Index(
    "idx_verify_attempts_agent_ts",
    VerificationAttempt.agent_id, VerificationAttempt.verified_at,
)


class EventLog(Base):
    """Per-event log for identity observable computation.

    Each row is one (challenge, response) interaction reported by the agent.
    Used by the identity engine to compute ICR, TWC, TTM, MVS, etc.
    """
    __tablename__ = "event_logs"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    event_count = Column(Integer, nullable=False)
    input_hash = Column(String, nullable=False)
    output_hash = Column(String, nullable=False)
    history_digest = Column(String, nullable=False)  # SHA256 hex of digest chain
    signature = Column(String, nullable=False)  # HMAC of event (backward compat)
    # ML-DSA-65 (FIPS 204 / Asqav-compatible) quantum-safe signature.
    # Nullable so existing events without ML-DSA remain valid.
    ml_dsa_signature = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    ts = Column(DateTime, default=datetime.utcnow, index=True)


Index("idx_eventlog_agent_ts", EventLog.agent_id, EventLog.ts)
Index("idx_eventlog_agent_count", EventLog.agent_id, EventLog.event_count)


class AgentBaseline(Base):
    """κ-engine V2 behavioral baseline for an agent (#62).

    A snapshot of an agent's *behavioral* distributions, computed over a
    window of recent events' ``metadata_json['behavioral']`` features (see
    #63). The κ-engine compares a fresh window of traffic against this
    baseline to detect drift — a model swap, a prompt-injection takeover,
    or organic concept drift all show up as a distributional shift in one
    or more features.

    One row per agent (latest baseline wins). ``features_json`` holds the
    per-feature distribution summaries + the raw sample arrays the
    statistical tests need (KS / Wasserstein want the samples, not just
    percentiles). Recomputed periodically as the agent accumulates events.

    Pre-existing events without behavioral metadata are simply skipped
    when building the baseline — forward-compatible with the #63 rollout.
    """
    __tablename__ = "agent_baseline"

    agent_id = Column(String, ForeignKey("agents.id"), primary_key=True)
    features_json = Column(JSON, nullable=False, default=dict)
    n_events = Column(Integer, nullable=False, default=0)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DriftEvent(Base):
    """A behavioral-drift detection emitted by the κ-engine V2 (#64).

    When ``compare_behavioral_to_baseline`` (κ-engine V2, #62) finds a
    fresh window of traffic that has drifted away from an agent's learned
    ``AgentBaseline`` (#62/#63), the alerts pipeline writes one row here.
    This is the durable carrier of the ``DRIFT_DETECTED`` event the
    landing copy promises ("raises alerts the moment something changes"):

      - it surfaces in the dashboard (the agent's "Behavioral changes"
        timeline — #65 renders it),
      - it triggers an email to the customer's ``EmailPreferences``
        recipient when ``drift_detected_enabled`` is on, and
      - it fires any active ``WebhookEndpoint`` with a
        ``behavioral_drift.detected`` payload.

    ``customer_id`` is denormalized (resolved via the agent's API key at
    write time) so the dashboard can list a customer's drift events
    without re-joining through ``api_keys`` on every read.

    Attribution: ``dominant_feature`` is the single most-out-of-baseline
    behavioral feature; ``baseline_value`` / ``current_value`` are its
    human-readable before/after summary; ``magnitude`` is the raw effect
    size (Wasserstein distance for continuous features, total-variation
    distance for categorical). ``attribution_json`` keeps the full
    per-feature verdict detail for the dashboard drill-down.

    ``acknowledged_at`` backs the dashboard's "mark as expected" action
    (#65): a customer confirming a drift is the new normal. We keep the
    row either way — it remains auditable evidence.
    """
    __tablename__ = "drift_events"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True, index=True)

    dominant_feature = Column(String, nullable=False)
    drift_score = Column(Float, nullable=False)
    magnitude = Column(Float, nullable=True)
    baseline_value = Column(String, nullable=True)   # human-readable before
    current_value = Column(String, nullable=True)    # human-readable after
    attribution_json = Column(JSON, default=dict)    # full per-feature detail

    window_size = Column(Integer, nullable=True)
    baseline_n_events = Column(Integer, nullable=True)

    notified_email = Column(Boolean, nullable=False, default=False)
    notified_webhook = Column(Boolean, nullable=False, default=False)
    acknowledged_at = Column(DateTime, nullable=True)  # "mark as expected" (#65)

    detected_at = Column(DateTime, default=datetime.utcnow, index=True)


Index("idx_drift_events_agent_ts", DriftEvent.agent_id, DriftEvent.detected_at)
Index("idx_drift_events_customer_ts", DriftEvent.customer_id, DriftEvent.detected_at)


class AgentState(Base):
    """Per-agent runtime state (digest chain head, current secret derivation, etc.)."""
    __tablename__ = "agent_state"

    agent_id = Column(String, ForeignKey("agents.id"), primary_key=True)
    history_digest = Column(String, nullable=False)  # latest digest
    event_count = Column(Integer, default=0)
    agent_secret = Column(String, nullable=False)  # the agent's HMAC secret
    last_event_at = Column(DateTime, nullable=True)
    active_alarms_json = Column(JSON, default=list)

    # UX-5.15.P / D-PROD.25 — Reset behavior baseline primitive.
    # When the customer accepts a behavior change as "the new normal", the
    # identity_engine ignores agent_observables with ts < last_baseline_reset_at
    # when computing the current shape. Pre-reset events are NOT deleted —
    # they remain as auditable evidence.
    # See docs/product/INTEGRATION-LIFECYCLE.md §4.
    last_baseline_reset_at = Column(DateTime, nullable=True)
    baseline_reset_count = Column(Integer, nullable=False, default=0)
    # Value of event_count at the moment of last reset. derive_trust
    # computes events_since_baseline = event_count - this, so the
    # behavioral state machine re-enters baselining cleanly. Null if
    # never reset (equivalent to 0 for the math).
    baseline_reset_event_count = Column(Integer, nullable=True)


class AgentObservable(Base):
    """Per-agent identity observables computed periodically over event_logs.

    Sprint 1 — Trinity observables: ICR + TWC + TTM (Crooks-calibrated β).
    Each row is one snapshot of the agent's identity observables at a given ts,
    computed over a window of `n_events` events.

    `identity_confidence` is the v0 aggregate score (0-100%) combining the
    trinity + n_events. Bumped each sprint as more observables come online.
    """
    __tablename__ = "agent_observables"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)

    # Trinity (Sprint 1)
    icr = Column(Float, nullable=True)            # Identity Conservation Ratio in [0, 1]
    twc = Column(Float, nullable=True)            # Thermodynamic Work of Coupling (nats)
    ttm = Column(Float, nullable=True)            # Thermal Time Modular (spectral gap)
    beta_crooks = Column(Float, nullable=True)    # β calibrated by Crooks symmetry

    # Window meta
    n_events = Column(Integer, nullable=False, default=0)
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)

    # Aggregator v0
    identity_confidence = Column(Float, nullable=True)  # 0.0 - 1.0

    # Optional structured details (per-observable diagnostics, e.g. n_star, alphabets)
    details_json = Column(JSON, default=dict)


Index("idx_observables_agent_ts", AgentObservable.agent_id, AgentObservable.ts)


class MemoryProbe(Base):
    """Memory Verification Score probes (R7.b protocol).

    Server periodically asks the agent: "prove you know your local_digest
    at event_count = target_t" via a nonce-bound proof. A genuine agent
    that maintains the digest chain locally can compute the proof; a
    fresh clone that took over later cannot reproduce digests from before
    the takeover — its proofs fail and MVS drops.

    Statuses:
      - pending:   issued, awaiting agent response.
      - responded: agent provided a proof (valid or not, see `valid`).
      - expired:   not answered within expires_at window.
    """
    __tablename__ = "memory_probes"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)

    target_event_count = Column(Integer, nullable=False)
    nonce = Column(String, nullable=False)              # hex (16 bytes random)
    expected_proof = Column(String, nullable=False)     # hex sha256
    agent_proof = Column(String, nullable=True)         # hex sha256, agent-supplied
    valid = Column(Boolean, nullable=True)              # null until responded

    status = Column(String, default="pending", index=True)
    issued_at = Column(DateTime, default=datetime.utcnow, index=True)
    responded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)

    # Sprint 7 / TLS (paper §8.3, R11-A) — time-locked challenge fields.
    # `history_digest_at_issue`: server's view of the digest chain at the
    #   exact moment the probe was minted. The response window derives
    #   deterministically from these bytes so legit and server agree
    #   without any extra negotiation.
    # `response_counter`: the agent's `event_count` at the moment it
    #   crafted its proof. Must land inside the derived window or the
    #   probe is flagged as a TLS miss (still counts toward MVS based on
    #   proof correctness — TLS is a separate signal).
    history_digest_at_issue = Column(String, nullable=True)
    response_counter = Column(Integer, nullable=True)

    # Sprint 7 / ADV (paper §8.6, R12) — adversarial probe detection.
    # A fraction of issued probes are deliberately malformed (e.g. a
    # truncated nonce, an out-of-range target_event_count). A legit
    # AIP-conformant agent detects the malformation and refuses to
    # answer, supplying `refusal_reason`. A naive attacker doesn't
    # recognize the protocol violation and either answers or stays silent.
    is_malformed = Column(Boolean, nullable=False, default=False)
    refusal_reason = Column(String, nullable=True)


Index("idx_probes_agent_status", MemoryProbe.agent_id, MemoryProbe.status)
Index("idx_probes_agent_issued", MemoryProbe.agent_id, MemoryProbe.issued_at)


class PredictionSubmission(Base):
    """Sprint 7 / PRS (paper §8.1, R10-D) — agent's pre-commitment to a
    distribution over its next response K events in the future.

    The agent submits via MCP `predict_response`:
        submitted_at_event_count: agent's `event_count` right now
        target_event_count = submitted_at_event_count + K_OFFSET
        predicted_distribution: list[float] length DEFAULT_ALPHABET
                                 (32), summing to ~1.0
    When the target event eventually arrives, the batch job resolves the
    submission by picking the realized response bucket and scoring
    hit/miss against the predicted distribution.
    """
    __tablename__ = "prediction_submissions"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    submitted_at_event_count = Column(Integer, nullable=False)
    target_event_count = Column(Integer, nullable=False)
    predicted_distribution = Column(JSON, nullable=False)
    realized_response_bucket = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


Index(
    "idx_predictions_agent_target",
    PredictionSubmission.agent_id, PredictionSubmission.target_event_count,
)
Index(
    "idx_predictions_agent_resolved",
    PredictionSubmission.agent_id, PredictionSubmission.resolved_at,
)


class AgentMeshPair(Base):
    """Sprint 7 / MCS (paper §8.4, R11-B) — pair of two same-customer
    agents that corroborate each other's state periodically.

    Canonical ordering: agent_a_id < agent_b_id lexicographically, so
    every unordered {A, B} maps to exactly one row regardless of which
    side initiated the pairing.
    """
    __tablename__ = "agent_mesh_pairs"

    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    agent_a_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    agent_b_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paused_at = Column(DateTime, nullable=True)


Index("idx_mesh_pairs_a_b", AgentMeshPair.agent_a_id, AgentMeshPair.agent_b_id)


class CorroborationPoint(Base):
    """One corroboration cycle for one mesh pair.

    Lifecycle:
      1. Either A or B submits first → row created with a_* or b_* set.
      2. The partner submits → opposite side filled.
      3. Server verifies both signatures + state agreement → sets
         `verified` and `resolved_at`.
      4. The batch job aggregates recent resolved cycles into MCS.

    A cycle is uniquely identified by (mesh_pair_id, cycle). The agent
    derives `cycle` deterministically from its event_count: cycle =
    event_count // CORROBORATION_INTERVAL. Both sides naturally land
    on the same cycle number because the interval is fixed.
    """
    __tablename__ = "corroboration_points"

    id = Column(String, primary_key=True)
    mesh_pair_id = Column(
        String, ForeignKey("agent_mesh_pairs.id"), nullable=False, index=True,
    )
    cycle = Column(Integer, nullable=False)

    a_state = Column(String, nullable=True)
    a_partner_state = Column(String, nullable=True)
    a_co_sig = Column(String, nullable=True)
    a_submitted_at = Column(DateTime, nullable=True)

    b_state = Column(String, nullable=True)
    b_partner_state = Column(String, nullable=True)
    b_co_sig = Column(String, nullable=True)
    b_submitted_at = Column(DateTime, nullable=True)

    verified = Column(Boolean, nullable=True)
    resolved_at = Column(DateTime, nullable=True)


Index(
    "idx_corroboration_pair_cycle",
    CorroborationPoint.mesh_pair_id, CorroborationPoint.cycle,
    unique=True,
)


class ZKHProof(Base):
    """Sprint 7 / ZKH (paper §8.5, R12) — Zero-Knowledge History via
    Merkle commit-reveal.

    Lifecycle:
      1. Agent calls `request_zkh_challenge` with its claimed
         `commit_root` (root of its local Merkle tree over history
         digests). Server validates the commit matches the chain it has
         in EventLog. If yes → picks random t_star, persists row, returns
         (t_star, nonce).
      2. Agent computes (digest_at_t_star, merkle_path) from its tree
         and submits via `submit_zkh_proof`.
      3. Server verifies path leads from claimed_digest to commit_root,
         AND claimed_digest matches its own stored history_digest at
         that event_count. Sets verified True/False.
    """
    __tablename__ = "zkh_proofs"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    commit_root = Column(String, nullable=False)
    server_root_at_issue = Column(String, nullable=False)
    t_star = Column(Integer, nullable=False)
    nonce = Column(String, nullable=False)
    claimed_digest = Column(String, nullable=True)
    merkle_path = Column(JSON, nullable=True)
    verified = Column(Boolean, nullable=True)
    rejection_reason = Column(String, nullable=True)
    issued_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)


Index("idx_zkh_agent_resolved", ZKHProof.agent_id, ZKHProof.resolved_at)
Index("idx_zkh_agent_issued", ZKHProof.agent_id, ZKHProof.issued_at)


class Watcher(Base):
    """Sprint 4 — zero-code bot watcher per agent.

    A watcher binds a customer's public bot (Telegram, Discord, Slack, X)
    to a Metalins agent so we can hash its public activity without the
    customer writing any SDK code. Polled by the watcher_job APScheduler
    job every `polling_interval_sec`.

    Token storage: envelope-encrypted (AES-256-GCM) with a KEK from GCP
    Secret Manager. Plaintext never lands in the DB. See
    docs/operations/WATCHER-ARCHITECTURE.md for the full design.
    """

    __tablename__ = "watchers"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)

    # 'telegram' | 'discord' | 'slack' | 'x'  (enforced by DB CHECK constraint)
    platform = Column(String, nullable=False)

    # AES-256-GCM ciphertext: hex(nonce_12 || ciphertext || tag_16)
    encrypted_token = Column(String, nullable=False)
    # KEK version label (e.g. "v1") for future rotation.
    encryption_key_ref = Column(String, nullable=False)

    # User-provided display label shown in the dashboard.
    display_name = Column(String, nullable=True)

    # 'pending' | 'active' | 'error' | 'paused'  (enforced by DB CHECK constraint)
    state = Column(String, nullable=False, default="pending", index=True)
    error_message = Column(String, nullable=True)

    # Polling
    polling_interval_sec = Column(Integer, nullable=False, default=60)
    last_polled_at = Column(DateTime, nullable=True)
    last_event_id = Column(String, nullable=True)  # platform-specific cursor
    events_logged = Column(Integer, nullable=False, default=0)

    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow)
    paused_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)  # soft delete


Index("idx_watchers_agent", Watcher.agent_id)
Index("idx_watchers_customer", Watcher.customer_id)


class AgentAnchor(Base):
    """External identity anchor for an agent. Sprint UX-5.9-G (#656).

    An anchor is a cryptographically-meaningful link from a Metalins
    agent to an identity that lives OUTSIDE Metalins — a public Telegram
    bot username, a GitHub user, a DNS-controlled domain. Without an
    anchor, "verified by Metalins" only means "this slug exists in our
    DB"; with one, the visitor can independently sanity-check on the
    anchored platform that the owner controls both ends.

    V1 supports only `type = "github"` via the gist challenge-response
    method:

      1. Customer calls /anchors/github/start → server mints a
         challenge_token + persists a pending row.
      2. Customer creates a public gist containing the token.
      3. Customer calls /anchors/github/verify with the gist URL.
         Server fetches the gist via GitHub's API, parses owner.login
         and file contents, validates the token is present, and on
         success persists `value = owner.login`, `verified_at = now()`.
      4. Verified anchors appear on the public verify page.

    Telegram anchors do NOT live in this table — they're derived
    on-the-fly from the Watcher row that already proves the bot was
    bound. See `_telegram_anchor_for_agent` in api/public.py.

    Future types: "dns", "x" (Twitter), "domain".
    """
    __tablename__ = "agent_anchors"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    type = Column(String, nullable=False)         # "github" today
    method = Column(String, nullable=False)       # "gist" for github
    value = Column(String, nullable=True)         # filled on verification
    challenge_token = Column(String, nullable=False)
    metadata_json = Column(JSON, default=dict)    # e.g. {"gist_id": "...", "gist_url": "..."}
    verified_at = Column(DateTime, nullable=True)
    last_check_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Index("idx_anchors_agent_type", AgentAnchor.agent_id, AgentAnchor.type)


class WebhookEndpoint(Base):
    """Customer-configured HTTPS endpoint for state-change alerts.

    Sprint UX-5.10-6 (#664). Diana's promise on the engineering-teams
    landing: "Webhook alerts when identity shifts". This is the storage
    side; firing lives in `services.webhook_delivery`.

    Lifecycle
    ---------
    1. Customer POSTs `{url}` to `/v1/agents/{id}/webhooks`. Server
       generates a random `secret` (32 bytes hex), returns it ONCE so
       the customer can store it and validate `X-Metalins-Signature`
       headers on deliveries. The plaintext is never returned again.
    2. Server stores the hashed secret in `secret_hash` only.
    3. When the agent's `verification_state` transitions to a level
       that requires attention (caution / action), the delivery
       service computes HMAC-SHA256 over the body, sends with header,
       and updates `last_delivery_at` + `last_delivery_status` +
       `last_delivery_error`.
    4. Customer can DELETE the row, which stops future deliveries.

    We deliberately don't store delivery history rows — that would
    grow unbounded. The single "last_*" trio gives enough visibility
    for the dashboard to show "Last delivery: 2h ago · 200 OK" and is
    enough for V1.
    """
    __tablename__ = "webhook_endpoints"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    secret_hash = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_delivery_at = Column(DateTime, nullable=True)
    last_delivery_status = Column(Integer, nullable=True)  # HTTP status code
    last_delivery_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # soft delete


Index("idx_webhooks_agent_active", WebhookEndpoint.agent_id, WebhookEndpoint.is_active)


class EmailPreferences(Base):
    """Per-customer outbound email preferences.

    Sprint UX-5.13 (2026-05-18). 1:1 with `customers` — at most one
    row per account. The row is OPTIONAL: if it doesn't exist, the
    server falls back to sane defaults (alerts on, alert_email = the
    customer's auth email).

    Why a separate table instead of columns on `customers`?
    --------------------------------------------------------
    The `customers` row is touched on every authenticated request
    (it's the `auth.users` shadow). Email prefs change ~once and are
    read at alert time. Keeping them in their own table means hot
    paths don't pay for cold columns. Same pattern as `webhook_endpoints`.

    Toggles
    -------
    `alerts_enabled` is the master switch. The per-event toggles are
    additive: an alert fires iff `alerts_enabled AND <per_event>_enabled`.
    `weekly_digest_enabled` defaults OFF because we haven't shipped
    the digest job yet; the column exists so we can flip it later
    without a migration.
    """
    __tablename__ = "email_preferences"

    customer_id              = Column(
        String, ForeignKey("customers.id"), primary_key=True
    )
    alert_email              = Column(String, nullable=True)
    alerts_enabled           = Column(Boolean, nullable=False, default=True)
    threshold_crossed_enabled = Column(Boolean, nullable=False, default=True)
    drift_detected_enabled   = Column(Boolean, nullable=False, default=True)
    weekly_digest_enabled    = Column(Boolean, nullable=False, default=False)
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class FlaggedEmail(Base):
    """An email address reported as an unsolicited sign-in request.

    Phase-2 anti-abuse (Jose, 2026-05-21). The magic-link email carries
    a "this wasn't me" link; clicking it (behind a Turnstile human
    check) records the address here. While a row stays uncleared, the
    dashboard login page refuses to send another magic link to it and
    routes the person to support instead.

    Deliberately NOT a hard ban. The report link travels inside an
    email anyone could have triggered, so the worst a flag can do is
    add a one-time "contact support" step. Support clears a flag by
    setting `cleared_at`; a fresh report re-opens it.

    `email` is always stored lowercased.
    """
    __tablename__ = "flagged_emails"

    email        = Column(String, primary_key=True)
    flagged_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    cleared_at   = Column(DateTime, nullable=True)
    report_count = Column(Integer, nullable=False, default=1)


class AccountDeletion(Base):
    """Audit row written when a customer deletes their own account.

    Free tier, immediate deletion (Jose, 2026-05-22). Deleting an
    account wipes every row tied to the customer — agents, events,
    event logs, observables, memory checks, proofs, keys, the customer
    record itself. We keep no user data afterwards. This table is the
    ONE thing that survives: an auditable record of which email
    deleted, when, and the reason — which the user is required to give.
    """
    __tablename__ = "account_deletions"

    id         = Column(String, primary_key=True)
    email      = Column(String, nullable=False, index=True)
    reason     = Column(String, nullable=False)
    deleted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
