#!/usr/bin/env bash
#
# smoke-a2a.sh — Sprint 6.4 cross-customer agent-to-agent smoke test.
#
# What it proves end-to-end against the live API:
#   1. A customer (auth'd via API key) can register an agent and obtain a
#      signed κ-proof.
#   2. ANY caller (no auth) can hit POST /v1/verify-proof and get
#      valid: true while the agent is alive.
#   3. After the customer hard-deletes the agent (POST /v1/agents/revoke,
#      Sprint 5 semantics), the SAME κ-proof now verifies invalid because
#      the issuing agent is no longer active.
#
# This is the contract we sell to relying parties on the landing:
#   "ask Metalins to confirm who's really on the other side, one signed
#    HTTP call, free for the verifier".
#
# Inputs (env):
#   METALINS_API_KEY   real API key (ml_live_...). Required.
#                      Mint one via the dashboard at /agents/[id]/keys
#                      if you don't have one yet.
#   API_BASE           override the server. Defaults to https://api.metalins.ai.
#
# Run:
#   export METALINS_API_KEY='ml_live_...'
#   bash server/scripts/smoke-a2a.sh
#
# Exit code 0 if every step passed. Non-zero if any assertion failed.

set -euo pipefail

API_BASE="${API_BASE:-https://api.metalins.ai}"

if [ -z "${METALINS_API_KEY:-}" ]; then
  echo "ERROR: METALINS_API_KEY not set. Export your ml_live_* key first." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: 'jq' required. brew install jq" >&2
  exit 1
fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { printf "${GREEN}✓${NC} %s\n" "$*"; }
info() { printf "${YELLOW}▶${NC} %s\n" "$*"; }
fail() { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

AUTH=(-H "Authorization: Bearer ${METALINS_API_KEY}")
JSON=(-H "Content-Type: application/json")

# ---------------------------------------------------------------------------
# Step 1: register a throwaway agent with deterministic behavior samples.
# The samples form the baseline that later verify-step responses must match.
# ---------------------------------------------------------------------------
info "Step 1 — Register throwaway agent"

REG_BODY=$(cat <<'JSON'
{
  "name": "smoke-a2a-throwaway",
  "model": "smoke-test",
  "framework": "smoke",
  "metadata": {"smoke": true},
  "behavior_samples": [
    {"challenge_id": "s1", "response": "alpha"},
    {"challenge_id": "s2", "response": "beta"},
    {"challenge_id": "s3", "response": "gamma"}
  ]
}
JSON
)

REG_RESP=$(curl -sS -X POST "${API_BASE}/v1/agents/register" \
  "${AUTH[@]}" "${JSON[@]}" -d "$REG_BODY")

AGENT_ID=$(printf "%s" "$REG_RESP" | jq -r '.agent_id // empty')
[ -n "$AGENT_ID" ] || fail "register failed. response: $REG_RESP"
ok "Registered agent: $AGENT_ID"

# Always try to clean up if something goes sideways.
cleanup() {
  if [ -n "${AGENT_ID:-}" ]; then
    curl -sS -X POST "${API_BASE}/v1/agents/revoke" \
      "${AUTH[@]}" "${JSON[@]}" \
      -d "{\"agent_id\":\"${AGENT_ID}\",\"reason\":\"smoke cleanup\"}" \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Step 2: request challenges + reply with the baseline responses replayed
# back. A real agent would compute fresh responses; for smoke we just want
# the score to be high enough that verified=true.
# ---------------------------------------------------------------------------
info "Step 2 — Request challenges + verify"

CH_RESP=$(curl -sS -X POST "${API_BASE}/v1/challenges/request" \
  "${AUTH[@]}" "${JSON[@]}" \
  -d "{\"agent_id\":\"${AGENT_ID}\",\"steps\":3}")

SESSION_ID=$(printf "%s" "$CH_RESP" | jq -r '.session_id // empty')
[ -n "$SESSION_ID" ] || fail "challenges request failed. response: $CH_RESP"

# Build the responses payload: for each challenge in the response, reply
# with the matching baseline value (alpha/beta/gamma). Since we registered
# challenge_ids s1/s2/s3, the server typically reuses those ids when
# generating challenges off-baseline.
RESPONSES_JSON=$(printf "%s" "$CH_RESP" | jq -c '
  .challenges
  | map({
      challenge_id: .id,
      response: (
        if (.id|test("s1")) then "alpha"
        elif (.id|test("s2")) then "beta"
        elif (.id|test("s3")) then "gamma"
        else "alpha" end
      )
    })
')

VERIFY_BODY=$(jq -n --arg aid "$AGENT_ID" --arg sid "$SESSION_ID" \
  --argjson responses "$RESPONSES_JSON" \
  '{agent_id:$aid, session_id:$sid, responses:$responses, scope:"smoke-a2a"}')

VERIFY_RESP=$(curl -sS -X POST "${API_BASE}/v1/verify" \
  "${AUTH[@]}" "${JSON[@]}" -d "$VERIFY_BODY")

KAPPA_PROOF=$(printf "%s" "$VERIFY_RESP" | jq -r '.kappa_proof // empty')
[ -n "$KAPPA_PROOF" ] || fail "verify did not return kappa_proof. response: $VERIFY_RESP"
SCORE=$(printf "%s" "$VERIFY_RESP" | jq -r '.score')
ok "Got κ-proof (JWT length: ${#KAPPA_PROOF}, score: $SCORE)"

# Sanity check the JWT shape: header.payload.signature, three base64url parts.
DOTS=$(printf "%s" "$KAPPA_PROOF" | tr -cd '.' | wc -c | tr -d ' ')
[ "$DOTS" = "2" ] || fail "κ-proof doesn't look like a JWT (dot count: $DOTS)"
ok "κ-proof has JWT shape (header.payload.signature)"

# ---------------------------------------------------------------------------
# Step 3: as an unauthenticated relying party (no Authorization header),
# verify the proof. Expect valid=true and still_active=true.
# ---------------------------------------------------------------------------
info "Step 3 — Public verify (no auth) — agent still alive"

VP_BODY=$(jq -n --arg kp "$KAPPA_PROOF" '{kappa_proof:$kp}')
VP_RESP=$(curl -sS -X POST "${API_BASE}/v1/verify-proof" \
  "${JSON[@]}" -d "$VP_BODY")

VALID=$(printf "%s" "$VP_RESP" | jq -r '.valid')
STILL_ACTIVE=$(printf "%s" "$VP_RESP" | jq -r '.still_active // false')
[ "$VALID" = "true" ] || fail "Expected valid=true while agent alive. Got: $VP_RESP"
[ "$STILL_ACTIVE" = "true" ] || fail "Expected still_active=true. Got: $VP_RESP"
ok "valid=true, still_active=true (cross-customer verify works)"

# ---------------------------------------------------------------------------
# Step 4: hard-delete the agent (Sprint 5 semantics — POST /v1/agents/revoke
# now wipes the row + all FK-pointing children).
# ---------------------------------------------------------------------------
info "Step 4 — Hard-delete the agent"

REV_RESP=$(curl -sS -X POST "${API_BASE}/v1/agents/revoke" \
  "${AUTH[@]}" "${JSON[@]}" \
  -d "{\"agent_id\":\"${AGENT_ID}\",\"reason\":\"smoke complete\"}")
REV_AGENT=$(printf "%s" "$REV_RESP" | jq -r '.agent_id // empty')
[ "$REV_AGENT" = "$AGENT_ID" ] || fail "revoke didn't echo agent_id. response: $REV_RESP"
# Clear AGENT_ID so the trap doesn't try to delete again.
AGENT_ID=""
ok "Agent hard-deleted"

# ---------------------------------------------------------------------------
# Step 5: same κ-proof, public verify again. Expect still_active=false
# (signature is still cryptographically valid — the JWT didn't expire —
# but the agent the proof asserts identity for is gone).
# ---------------------------------------------------------------------------
info "Step 5 — Public verify AFTER delete — should report not active"

VP2_RESP=$(curl -sS -X POST "${API_BASE}/v1/verify-proof" \
  "${JSON[@]}" -d "$VP_BODY")

VALID2=$(printf "%s" "$VP2_RESP" | jq -r '.valid')
STILL_ACTIVE2=$(printf "%s" "$VP2_RESP" | jq -r '.still_active // false')

# The current public.py logic:
#   - Signature still verifies (the master key didn't change).
#   - Revocation list lookup: the JWT's jti isn't in revocations table
#     (revocations are populated separately, not by agent delete).
#   - still_active flips to false because db.query(Agent).filter(id=...)
#     returns None after the hard-delete (or .is_active=False).
#
# So valid stays "true" by the response schema BUT still_active=false. The
# relying party policy should refuse on still_active=false.
[ "$STILL_ACTIVE2" = "false" ] || fail "After delete: expected still_active=false. Got: $VP2_RESP"
ok "valid=${VALID2}, still_active=false — relying party correctly informed"

echo
printf "${GREEN}═══════════════════════════════════════════════════${NC}\n"
printf "${GREEN}✅ A2A SMOKE PASSED${NC}\n"
printf "${GREEN}═══════════════════════════════════════════════════${NC}\n"
echo
echo "Flow validated:"
echo "  • customer X registers + verifies → κ-proof issued"
echo "  • unauthenticated relying party calls /v1/verify-proof → valid + active"
echo "  • customer X hard-deletes the agent"
echo "  • same κ-proof now reports still_active=false to the relying party"
echo
echo "This is the contract on the landing's #1 use-case card. Tested green."
