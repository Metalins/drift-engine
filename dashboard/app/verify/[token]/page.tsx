/**
 * Public verification page — `/verify/<agent_id>`.
 *
 * Sprint UX-5.5f (#629). Carlos pastes this in his bot bio, or Sofía
 * embeds the badge linking here.
 *
 * Sprint UX-5.7a (#634): render moved to `components/VerifyCardSet`
 * so `/v/<slug>` and `/verify/<id>` share the same look.
 *
 * Sprint UX-5.11 R2 / R2.4a (2026-05-18): the page now accepts a
 * `?proof=<jwt>` query parameter and falls into live mode (reference
 * + freshness) when valid. See the sibling `/v/[slug]/page.tsx` for
 * the full rationale.
 */
import {
  getPublicAgent,
  verifyProof,
  lookupProofById,
  ApiError,
  type VerifyProofResult,
} from "@/lib/api";
import { VerifyCardSet, type VerifyResult } from "@/components/VerifyCardSet";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ token: string }>;
  /** Sprint UX-5.11 R2 / R2.7 — see /v/[slug]/page.tsx for the
   * rationale on accepting both `?p` (short proof_id) and `?proof` (JWT). */
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

export default async function VerifyByIdPage({
  params,
  searchParams,
}: PageProps) {
  const { token } = await params;
  const { p, proof } = await searchParams;
  const agentId = decodeURIComponent(token);
  const proofId = typeof p === "string" ? p : undefined;
  const proofToken = typeof proof === "string" ? proof : undefined;

  let result: VerifyResult;
  try {
    const info = await getPublicAgent(agentId);
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
