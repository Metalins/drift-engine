/**
 * Proxy: POST /api/agents/[id]/recompute → Metalins recompute endpoint.
 * Sprint 6 (2026-05-16): on-demand Identity Confidence refresh button.
 *
 * Forwards the user's Supabase JWT and surfaces the server's 429/412
 * responses unchanged so the client component can render the right state
 * (cooldown countdown, "send activity first", etc.).
 */
import { NextRequest, NextResponse } from "next/server";
import { recomputeAgent, ApiError } from "@/lib/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await recomputeAgent(id);
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
