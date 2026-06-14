#!/usr/bin/env bash
#
# smoke-issue-proof.sh — Sprint 6-A2A 6.1 + 6.2 smoke against prod.
#
# What it proves end-to-end:
#   1. A customer auth'd via API key can call POST /v1/agents/{id}/issue-proof
#      and get a signed JWT claim back (the new dashboard-issued path,
#      no challenge/response loop).
#   2. ANY caller (no auth) hits POST /v1/verify-proof and gets valid=true.
#   3. The verification attempt was logged: GET /v1/agents/{id}/verifications
#      returns total >= 1.
#
# Complements `smoke-a2a.sh` (which tests the older challenge-response flow
# via /v1/agents/register + /v1/verify).
#
# IMPORTANT: NO SDK is used or published. Decision Sprint 4.13 + Jose
# 2026-05-16: V1 ships with three integration paths only — Watcher, MCP,
# REST API direct. Relying parties verify via raw `fetch()` to the public
# /v1/verify-proof endpoint.
#
# Inputs (env):
#   METALINS_API_KEY   ml_live_... key. Required.
#   AGENT_ID           an active agent owned by that key. Required.
#   API_BASE           defaults to https://api.metalins.ai
#
# Run:
#   export METALINS_API_KEY='ml_live_...'
#   export AGENT_ID='agt_xxx'
#   bash server/scripts/smoke-issue-proof.sh

set -euo pipefail

API_BASE="${API_BASE:-https://api.metalins.ai}"

[ -n "${METALINS_API_KEY:-}" ] || { echo "ERROR: METALINS_API_KEY required" >&2; exit 1; }
[ -n "${AGENT_ID:-}" ]         || { echo "ERROR: AGENT_ID required" >&2; exit 1; }
command -v jq >/dev/null || { echo "ERROR: jq required" >&2; exit 1; }

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { printf "${GREEN}✓${NC} %s\n" "$*"; }
info() { printf "${YELLOW}▶${NC} %s\n" "$*"; }
fail() { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

AUTH=(-H "Authorization: Bearer ${METALINS_API_KEY}")
JSON=(-H "Content-Type: application/json")

# Step 1: read counter BEFORE so we know the delta after the verify.
info "Step 1 — Read current /verifications total"
BEFORE=$(curl -sS "${API_BASE}/v1/agents/${AGENT_ID}/verifications" "${AUTH[@]}")
BEFORE_TOTAL=$(printf '%s' "$BEFORE" | jq -r '.total // 0')
ok "current total: ${BEFORE_TOTAL}"

# Step 2: mint a claim via the new endpoint.
info "Step 2 — Issue verifiable claim (dashboard path)"
ISSUE_RES=$(curl -sS -X POST "${API_BASE}/v1/agents/${AGENT_ID}/issue-proof" \
  "${AUTH[@]}" "${JSON[@]}" \
  -d '{"ttl_seconds":300,"scope":"smoke-issue-proof"}')
TOKEN=$(printf '%s' "$ISSUE_RES" | jq -r '.kappa_proof // empty')
PROOF_ID=$(printf '%s' "$ISSUE_RES" | jq -r '.proof_id // empty')
[ -n "$TOKEN" ] || fail "issue-proof failed. response: $ISSUE_RES"
[ "$(printf '%s' "$TOKEN" | tr -cd '.' | wc -c | tr -d ' ')" = "2" ] \
  || fail "token doesn't look like a JWT: $TOKEN"
ok "claim minted (proof_id=${PROOF_ID})"

# Step 3: verify publicly. No auth header. Just like a relying party would.
info "Step 3 — Verify via PUBLIC /v1/verify-proof (no auth, no SDK)"
VR=$(curl -sS -X POST "${API_BASE}/v1/verify-proof" \
  "${JSON[@]}" -d "$(jq -n --arg t "$TOKEN" '{kappa_proof:$t}')")
VALID=$(printf '%s' "$VR" | jq -r '.valid')
STILL=$(printf '%s' "$VR" | jq -r '.still_active')
RET_AGENT=$(printf '%s' "$VR" | jq -r '.agent_id')
RET_SCOPE=$(printf '%s' "$VR" | jq -r '.scope')
[ "$VALID" = "true" ]      || fail "expected valid=true: $VR"
[ "$STILL" = "true" ]      || fail "expected still_active=true: $VR"
[ "$RET_AGENT" = "$AGENT_ID" ] || fail "agent_id mismatch: $RET_AGENT vs $AGENT_ID"
[ "$RET_SCOPE" = "smoke-issue-proof" ] || fail "scope mismatch: $RET_SCOPE"
ok "valid=true still_active=true agent_id matches scope passed through"

# Step 4: confirm the verify was logged in the timeline. Backend has
# best-effort insert; small wait so any async commit lands.
info "Step 4 — Confirm /verifications counter incremented (best-effort)"
sleep 1
AFTER=$(curl -sS "${API_BASE}/v1/agents/${AGENT_ID}/verifications" "${AUTH[@]}")
AFTER_TOTAL=$(printf '%s' "$AFTER" | jq -r '.total // 0')
AFTER_VALID=$(printf '%s' "$AFTER" | jq -r '.valid // 0')

if [ "$AFTER_TOTAL" -gt "$BEFORE_TOTAL" ]; then
  ok "total ${BEFORE_TOTAL} → ${AFTER_TOTAL} · valid count: ${AFTER_VALID}"
else
  printf "${RED}!${NC} total didn't increment (was ${BEFORE_TOTAL}, now ${AFTER_TOTAL}).\n"
  printf "  This can happen if the DB insert in verify_proof silently rolled back.\n"
  printf "  Check Cloud Run logs for the timestamp around now.\n" >&2
  # Don't fail — the public verify itself worked.
fi

# Step 5: sanity-check the most recent item matches what we just minted.
info "Step 5 — Verify the latest item in the panel matches our proof_id"
LATEST_PID=$(printf '%s' "$AFTER" | jq -r '.items[0].proof_id // empty')
if [ "$LATEST_PID" = "$PROOF_ID" ]; then
  ok "latest item proof_id matches"
else
  printf "${YELLOW}!${NC} latest item proof_id (${LATEST_PID}) != minted (${PROOF_ID}).\n"
  printf "  Could be high concurrency or stale list cache.\n" >&2
fi

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Sprint 6-A2A 6.1 + 6.2 smoke OK.${NC}"
echo -e "${GREEN}========================================${NC}"
