/**
 * Proxy: POST /api/agents/[id]/claim-slug → Metalins.
 *
 * Sprint UX-5.11 R2 / R2.3b (2026-05-18). After verifying an anchor
 * (Telegram bot bio, GitHub gist, DNS), the customer can claim a
 * `/v/<slug>` derived from that anchor's value. This route exists so
 * the Client-Component AnchorsManager can hit the backend through the
 * Supabase session cookie (lib/api.ts is server-only).
 */
import { NextRequest, NextResponse } from "next/server";
import { claimSlugFromAnchor, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = (await request.json()) as { anchor_id: string };
    const result = await claimSlugFromAnchor(id, body.anchor_id);
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
