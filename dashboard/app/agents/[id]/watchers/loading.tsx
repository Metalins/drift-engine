/**
 * Loading skeleton for /agents/[id]/watchers — Sprint 4.16.
 */
export default function WatchersLoading() {
  return (
    <main className="space-y-6">
      <div className="space-y-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <Skeleton className="h-10 w-40 rounded-md" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="h-24 rounded-lg" />
      </div>
    </main>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-muted ${className}`} aria-hidden />
  );
}
