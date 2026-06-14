/**
 * Proxy: POST /api/agents/[id]/disconnect-mcp → Metalins server.
 * Sprint 6.4 / #575.
 */
import { NextRequest, NextResponse } from "next/server";
import { disconnectMcp, ApiError } from "@/lib/api";

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
    const result = await disconnectMcp(id, confirmationName);
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
