/**
 * Proxy: POST /api/agents/[id]/reissue-secret → Metalins server.
 * UX-5.17 #505 / #931.
 *
 * Mirrors the reset-baseline proxy pattern. The client-side reissue
 * panel calls this local route so the @supabase/ssr cookie machinery
 * (in lib/api.ts → lib/supabase/server.ts) doesn't get bundled into
 * the client chunk.
 *
 * Re-keys the agent: brand-new agent_secret, fresh cryptographic
 * genesis, verification history wiped, tier reset. Confirm-by-name
 * guard enforced server-side; we forward whatever the user typed.
 */
import { NextRequest, NextResponse } from "next/server";
import { reissueSecret, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const confirmationName = body?.confirmation_name;
    if (typeof confirmationName !== "string") {
      return NextResponse.json(
        { detail: "confirmation_name (string) required" },
        { status: 400 },
      );
    }
    const result = await reissueSecret(id, confirmationName);
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Unknown error" },
      { status: 500 },
    );
  }
}
