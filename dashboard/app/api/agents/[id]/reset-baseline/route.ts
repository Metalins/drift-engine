/**
 * Proxy: POST /api/agents/[id]/reset-baseline → Metalins server.
 * UX-5.15.P / D-PROD.25.
 *
 * Mirrors the disconnect-mcp proxy pattern. Client-side DriftAlert
 * calls this local route so the @supabase/ssr cookie machinery (in
 * lib/api.ts → lib/supabase/server.ts) doesn't get bundled into the
 * client chunk.
 */
import { NextRequest, NextResponse } from "next/server";
import { resetBaseline, ApiError } from "@/lib/api";

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
    const result = await resetBaseline(id, confirmationName);
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
