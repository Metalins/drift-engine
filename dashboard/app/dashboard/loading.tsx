/**
 * Loading skeleton for /dashboard — Sprint 4.16.
 *
 * Renders instantly via Next.js streaming while the Server Component
 * fetches /v1/agents. The skeleton matches the real layout so the
 * page doesn't jump when content lands.
 */
export default function DashboardLoading() {
  return (
    <main className="space-y-6">
      <header className="flex items-end justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-9 w-20" />
        </div>
      </header>

      <Skeleton className="h-20 w-full rounded-lg" />

      <ul className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <li key={i} className="rounded-lg border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 space-y-2">
                <Skeleton className="h-5 w-48" />
                <Skeleton className="h-3 w-72" />
                <Skeleton className="h-3 w-40" />
              </div>
              <Skeleton className="h-6 w-14 rounded-full" />
            </div>
            <div className="mt-3 flex gap-2 border-t pt-3">
              <Skeleton className="h-7 w-28 rounded-md" />
              <Skeleton className="h-7 w-20 rounded-md" />
            </div>
          </li>
        ))}
      </ul>
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
