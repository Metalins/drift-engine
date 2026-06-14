/**
 * Loading skeleton for /agents/[id] — Sprint 4.16.
 *
 * Mirrors the detail page layout (confidence gauge + observable cards +
 * probes + batch windows) so the page doesn't jump when content arrives.
 */
export default function AgentDetailLoading() {
  return (
    <main className="space-y-8">
      {/* Header */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-24" />
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-9 w-72" />
            <Skeleton className="h-4 w-96" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-36" />
            <Skeleton className="h-9 w-24" />
          </div>
        </div>
      </div>

      {/* Confidence + metadata grid */}
      <section className="grid gap-6 md:grid-cols-2">
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </section>

      {/* Observable cards */}
      <section className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-lg" />
        ))}
      </section>

      {/* Probes + batch windows */}
      <section className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-72 rounded-lg" />
        <Skeleton className="h-72 rounded-lg" />
      </section>

      <Skeleton className="h-64 rounded-lg" />
    </main>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-muted ${className}`}
      aria-hidden
    />
  );
}
