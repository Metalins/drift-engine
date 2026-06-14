/**
 * 404 boundary for the agent detail route. Renders when the API returns
 * 404 for the requested agent_id (i.e. the server-side fetch caller calls
 * `notFound()` from app/agents/[id]/page.tsx).
 */
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="space-y-4">
      <Link
        href="/"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Back to agents
      </Link>
      <div className="rounded-md border bg-card p-6">
        <h1 className="text-xl font-semibold">Agent not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This agent_id is not on your account, or it has never been registered.
          Double-check the URL.
        </p>
      </div>
    </main>
  );
}
