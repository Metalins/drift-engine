/**
 * Public verification page — `/v/<slug>` (human-readable form).
 *
 * Sprint UX-5.7a (#634). Companion to `/verify/<agent_id>`.
 *
 * Sprint UX-5.11 R2 / R2.4a (2026-05-18). The page now has TWO modes
 * driven by the `?proof=<jwt>` query parameter:
 *
 *   • Static mode (no `?proof=`): renders the identity card with a
 *     prominent "Ask for a proof with YOUR reference" CTA. This is
 *     the link Carlos pastes in his bot bio. It's useful for casual
 *     browsing but a savvy visitor will want a reference-bound proof.
 *
 *   • Live mode (`?proof=<jwt>` validates): renders the reference
 *     (scope), signed-at timestamp, and operator identity in green.
 *     This is the link Carlos generates fresh per-verifier (via
 *     IssueClaim) — the visitor compares the displayed reference
 *     against the word they asked Carlos to include.
 *
 * Both routes (`/v/<slug>` and `/verify/<agent_id>`) accept `?proof=`
 * identically. The verify-proof endpoint is unauth and idempotent.
 */
import {
  getPublicAgentBySlug,
  verifyProof,
  lookupProofById,
  ApiError,
  type VerifyProofResult,
} from "@/lib/api";
import { VerifyCardSet, type VerifyResult } from "@/components/VerifyCardSet";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ slug: string }>;
  /** Sprint UX-5.11 R2 / R2.7 (2026-05-18). Verify URLs accept two
   * proof-attachment formats:
   *   - `?p=<proof_id>` — short, ~15 chars. The page resolves the
   *     proof_id to its stored JWT server-side then validates. This
   *     is what the IssueClaim UI generates for humans sharing in
   *     chat / bios. Default format.
   *   - `?proof=<JWT>`  — the full ~700-char JWT inline. Kept for A2A
   *     integrators that obtain the JWT directly and want the verify
   *     page to render it without an extra round-trip.
   * If both are present, `?p` wins (it's the canonical short form). */
  searchParams: Promise<{
    p?: string | string[];
    proof?: string | string[];
  }>;
}

export const metadata = {
  title: "Verified by Metalins",
  description:
    "Cryptographic identity verification for an AI agent registered on Metalins.",
};

export default async function VerifyBySlugPage({
  params,
  searchParams,
}: PageProps) {
  const { slug } = await params;
  const { p, proof } = await searchParams;
  const decoded = decodeURIComponent(slug);
  const proofId = typeof p === "string" ? p : undefined;
  const proofToken = typeof proof === "string" ? proof : undefined;

  let result: VerifyResult;
  try {
    const info = await getPublicAgentBySlug(decoded);
    result = { kind: "ok", info };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      result = { kind: "not_found" };
    } else {
      result = {
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      };
    }
  }

  // Resolve the JWT. Short form `?p=<id>` takes priority — that's the
  // canonical sharing format. Fall through to `?proof=<JWT>` for A2A
  // integrators that pasted the token directly. If neither resolves,
  // we render in static mode below.
  let proofResult: VerifyProofResult | null = null;
  let resolvedJwt: string | undefined = proofToken;
  if (proofId && result.kind === "ok") {
    try {
      const lookup = await lookupProofById(proofId);
      if (lookup) {
        resolvedJwt = lookup.kappa_proof;
      } else {
        proofResult = { valid: false, reason: "proof_id_not_found" };
      }
    } catch {
      proofResult = { valid: false, reason: "verifier_unreachable" };
    }
  }
  if (resolvedJwt && result.kind === "ok" && !proofResult) {
    try {
      proofResult = await verifyProof(resolvedJwt);
    } catch {
      proofResult = { valid: false, reason: "verifier_unreachable" };
    }
  }

  return <VerifyCardSet result={result} proof={proofResult} />;
}
