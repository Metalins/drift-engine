/**
 * Proxy: POST /api/agents/[id]/api-keys → server's create-key endpoint.
 * Forwards the body verbatim and uses the Supabase session JWT as bearer.
 */
import { NextRequest, NextResponse } from "next/server";
import { createAgentKey, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const result = await createAgentKey(id, {
      name: body.name,
      description: body.description,
    });
    return NextResponse.json(result, { status: 201 });
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
