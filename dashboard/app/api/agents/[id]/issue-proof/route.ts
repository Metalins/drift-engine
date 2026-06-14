/**
 * Proxy: POST /api/agents/[id]/issue-proof → Metalins server.
 * Sprint 6-A2A 6.1.
 *
 * Client components can't import `lib/api.ts` directly because it
 * depends on `next/headers` (server-only). This route handler runs
 * in the server context, forwards the request with the customer's
 * session JWT, and returns the JSON.
 */
import { NextRequest, NextResponse } from "next/server";
import { issueProof, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const ttlSeconds = body?.ttl_seconds;
    const scope = body?.scope;

    if (typeof ttlSeconds !== "number") {
      return NextResponse.json(
        { detail: "ttl_seconds (number) required" },
        { status: 400 },
      );
    }
    if (scope !== undefined && scope !== null && typeof scope !== "string") {
      return NextResponse.json(
        { detail: "scope must be a string or omitted" },
        { status: 400 },
      );
    }

    const result = await issueProof(id, {
      ttl_seconds: ttlSeconds,
      scope: typeof scope === "string" && scope.length > 0 ? scope : undefined,
    });
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
