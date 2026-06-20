/**
 * Proxy: POST /api/agents/[id]/reconnect-mcp → Metalins server.
 * Sprint 6.4 / #575. No body — just re-enables the MCP surface.
 */
import { NextRequest, NextResponse } from "next/server";
import { reconnectMcp, ApiError } from "@/lib/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await reconnectMcp(id);
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
