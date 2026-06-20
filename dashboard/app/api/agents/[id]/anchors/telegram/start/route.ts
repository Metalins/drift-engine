/**
 * Proxy: POST /api/agents/[id]/anchors/telegram/start → Metalins.
 *
 * Sprint UX-5.11 R2 / bug-r1-carlos-1 (2026-05-18). Mirrors the GitHub
 * gist proxy — exists so the AnchorsManager Client Component can call
 * the backend without importing the server-only `lib/api.ts` helpers
 * (which read `next/headers` for the Supabase session cookie).
 */
import { NextRequest, NextResponse } from "next/server";
import { startTelegramAnchor, ApiError } from "@/lib/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await startTelegramAnchor(id);
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
