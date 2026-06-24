/**
 * VerificationsPanel — Sprint 6-A2A 6.2.
 *
 * Server Component (default — no "use client"). Shows the latest
 * verification attempts received for this agent: counter on top, recent
 * timeline below.
 *
 * Privacy: we never recorded the relying-party IP. Each row only shows
 * timestamp + outcome + scope.
 *
 * D-PROD.18: customer copy says "verifications served" / "identity
 * claim verified", never "JWT" / "JWKS" / "RS256".
 */
import { getVerifications, type VerificationAttempt } from "@/lib/api";

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.max(0, Math.floor((now - then) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function reasonLabel(item: VerificationAttempt): string {
  if (item.valid && !item.reason) return "Verified";
  if (item.valid && item.reason === "agent_inactive")
    return "Verified — agent inactive";
  switch (item.reason) {
    case "signature_invalid":
      return "Signature invalid";
    case "revoked":
      return "Revoked";
    case "agent_inactive":
      return "Agent inactive";
    default:
      return item.reason || (item.valid ? "Verified" : "Rejected");
  }
}

export async function VerificationsPanel({ agentId }: { agentId: string }) {
  let data;
  try {
    data = await getVerifications(agentId, { limit: 25 });
  } catch {
    return null;
  }

  if (data.total === 0) {
    return (
      <section className="rounded-lg border bg-card p-5">
        <h2 className="font-medium">Verifications served</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          No one has verified this agent&apos;s identity yet. Once someone
          (a service, an app, another agent) checks a claim you&apos;ve
          issued, it&apos;ll show up here.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="font-medium">Verifications served</h2>
        <div className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{data.valid}</span>{" "}
          valid · {data.total} total
        </div>
      </div>

      <ol className="space-y-2">
        {data.items.map((item) => (
          <li
            key={item.id}
            className="flex items-center justify-between gap-3 rounded-md border bg-background/30 px-3 py-2 text-sm"
          >
            <div className="flex items-center gap-3 min-w-0">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${
                  item.valid && !item.reason
                    ? "bg-emerald-500"
                    : item.valid
                    ? "bg-amber-500"
                    : "bg-destructive"
                }`}
                aria-hidden="true"
              />
              <span className="truncate font-medium">{reasonLabel(item)}</span>
              {item.scope && (
                <code className="hidden truncate rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
                  {item.scope}
                </code>
              )}
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">
              {relativeTime(item.verified_at)}
            </span>
          </li>
        ))}
      </ol>

      {data.total > data.items.length && (
        <p className="mt-3 text-xs text-muted-foreground">
          Showing the most recent {data.items.length} of {data.total}.
        </p>
      )}
    </section>
  );
}
