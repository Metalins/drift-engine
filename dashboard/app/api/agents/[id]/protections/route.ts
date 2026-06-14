/**
 * Proxy: GET /api/agents/[id]/protections → Metalins protections endpoint.
 * Sprint UX-5.15.UX1 — consumed by ProtectionsChecklist's 30s auto-refresh
 * poll. Cannot import `getAgentProtections` from `@/lib/api` directly in
 * the client component because lib/api.ts pulls in the server-side
 * supabase helper (uses next/headers). Standard proxy pattern.
 */
import { NextRequest, NextResponse } from "next/server";
import { getAgentProtections, ApiError } from "@/lib/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await getAgentProtections(id);
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
