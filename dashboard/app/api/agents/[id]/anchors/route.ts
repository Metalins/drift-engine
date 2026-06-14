/**
 * Proxy: GET /api/agents/[id]/anchors → Metalins list anchors.
 *
 * Sprint UX-5.9-G. Lives as a Next route handler so Client Components
 * can fetch anchors without importing the server-only `@/lib/api`
 * helpers (those pull in `next/headers`, which Turbopack refuses to
 * bundle into a Client Component).
 */
import { NextRequest, NextResponse } from "next/server";
import { listAnchors, ApiError } from "@/lib/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await listAnchors(id);
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
