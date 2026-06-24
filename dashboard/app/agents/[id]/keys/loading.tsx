/**
 * Loading skeleton for /agents/[id]/keys — Sprint 4.16.
 */
export default function KeysLoading() {
  return (
    <main className="space-y-6">
      <div className="space-y-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <Skeleton className="h-10 w-40 rounded-md" />
      <ul className="space-y-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <li key={i}>
            <Skeleton className="h-20 rounded-lg" />
          </li>
        ))}
      </ul>
    </main>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-muted ${className}`} aria-hidden />
  );
}
