#!/usr/bin/env bash
# gh-122 — end-to-end smoke test for the self-hosted docker-compose stack.
#
# Brings the stack up from scratch, then exercises the full first-run path a
# self-hosting operator hits: health → admin login → API-key-authed internal
# API (list / register / get agent). This is the regression guard for gh-121
# (dev API key was created without customer_id, so every /internal/v1/* call
# 409'd).
#
# Usage (from the repo root):
#
#   sudo ./server/smoke-test-docker.sh
#
# Requires: docker compose, curl, python3. Leaves the stack DOWN with volumes
# removed on success. Exits non-zero on the first failed assertion.
set -euo pipefail

# Resolve repo root (this script lives in server/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BASE_URL="http://localhost:8000"
ADMIN_EMAIL="admin@localhost"
ADMIN_PASSWORD="changeme"
DC="docker compose"

pass() { echo "  ✅ $1"; }
fail() { echo "  ❌ $1" >&2; echo "FAILED — dumping server logs:" >&2; $DC logs server 2>&1 | tail -40 >&2; cleanup; exit 1; }
cleanup() { echo "[smoke] Tearing down stack (down -v)..."; $DC down -v >/dev/null 2>&1 || true; }

echo "[smoke] 1/6 — Fresh stack: down -v, build, up"
$DC down -v >/dev/null 2>&1 || true
$DC build
$DC up -d

echo "[smoke] Waiting for the server to report healthy (up to 90s)..."
HEALTHY=""
for _ in $(seq 1 30); do
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
  sleep 3
done
[ -n "$HEALTHY" ] || fail "server never became reachable at $BASE_URL/health"

echo "[smoke] 2/6 — GET /health"
HEALTH=$(curl -fsS "$BASE_URL/health")
echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok', d; print('     ',d)" \
  && pass "/health → status ok" || fail "/health did not return status=ok (got: $HEALTH)"

echo "[smoke] 3/6 — POST /auth/login ($ADMIN_EMAIL)"
LOGIN=$(curl -fsS -X POST "$BASE_URL/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}") || fail "login request failed"
JWT=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])") \
  || fail "login response had no access_token (got: $LOGIN)"
[ -n "$JWT" ] && pass "login returned a JWT" || fail "empty JWT"

echo "[smoke] 4/6 — Extract dev API key from server logs"
# init_db.py prints the raw key once on first boot: 'ml_dev_<token>'.
API_KEY=$($DC logs server 2>&1 | grep -oE 'ml_dev_[A-Za-z0-9_-]+' | head -1 || true)
[ -n "$API_KEY" ] && pass "found dev API key in logs" || fail "could not find ml_dev_* key in server logs"

echo "[smoke] 4b — GET /internal/v1/agents (API key) → must NOT 409 (gh-121 guard)"
AGENTS=$(curl -fsS "$BASE_URL/internal/v1/agents" -H "Authorization: Bearer $API_KEY") \
  || fail "GET /internal/v1/agents failed (gh-121 regression — key not linked to customer?)"
echo "$AGENTS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
items = d if isinstance(d,list) else d.get('agents', d.get('items', d))
n = len(items) if isinstance(items,list) else '?'
print('      agents listed:', n)
" && pass "/internal/v1/agents returned a list (key linked to customer)" || fail "agents list not parseable: $AGENTS"

echo "[smoke] 5/6 — POST /internal/v1/agents/register"
REG=$(curl -fsS -X POST "$BASE_URL/internal/v1/agents/register" \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke-test-agent","model":"gpt-4o","framework":"smoke"}') \
  || fail "agent register failed"
AGENT_ID=$(echo "$REG" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('agent_id') or d.get('id'))") \
  || fail "register response had no agent id (got: $REG)"
[ -n "$AGENT_ID" ] && pass "registered agent: $AGENT_ID" || fail "empty agent id"

echo "[smoke] 6/6 — GET /internal/v1/agents/$AGENT_ID"
DETAIL=$(curl -fsS "$BASE_URL/internal/v1/agents/$AGENT_ID" -H "Authorization: Bearer $API_KEY") \
  || fail "agent detail fetch failed"
echo "$DETAIL" | python3 -c "
import sys,json
d=json.load(sys.stdin)
assert d.get('name')=='smoke-test-agent', d
print('      name:', d.get('name'), '| id:', d.get('id') or d.get('agent_id'))
" && pass "agent detail matches" || fail "agent detail mismatch: $DETAIL"

echo
echo "[smoke] ✅ ALL CHECKS PASSED"
cleanup
echo "[smoke] Done."
