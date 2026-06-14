/**
 * Proxy: POST /api/agents/[id]/revoke → Metalins revoke-agent.
 * Sprint 4.11.
 */
import { NextRequest, NextResponse } from "next/server";
import { revokeAgent, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const result = await revokeAgent(id, body?.reason);
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
