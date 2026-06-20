/**
 * Proxy: POST /api/agents/[id]/anchors/telegram/verify → Metalins.
 *
 * Sprint UX-5.11 R2 / bug-r1-carlos-1 (2026-05-18).
 */
import { NextRequest, NextResponse } from "next/server";
import { verifyTelegramAnchor, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = (await request.json()) as {
      anchor_id: string;
      telegram_username: string;
    };
    const result = await verifyTelegramAnchor(id, body);
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
