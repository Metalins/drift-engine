/**
 * PendingProbesPanel — the action queue for an agent. Shows open challenges
 * (issued, not yet responded) and visually distinguishes ones that have
 * already passed their expiry deadline (these will never validate again,
 * but we surface them so the operator notices the agent is silent).
 *
 * Sprint 3a renders this in the agent detail page; Sprint 3b will wire it
 * to a "respond" action against POST /v1/agents/{id}/probes/{probe_id}/respond.
 */
import type { ProbeRow } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { timeAgo, timeUntil } from "@/lib/utils";

interface Props {
  probes: ProbeRow[];
  emptyMessage?: string;
}

export function PendingProbesPanel({
  probes,
  emptyMessage = "No pending probes — agent is up to date.",
}: Props) {
  if (!probes.length) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
  }
  return (
    <ul className="space-y-3">
      {probes.map((p) => {
        const expiresIso = p.expires_at;
        const isExpired = expiresIso
          ? new Date(expiresIso).getTime() < Date.now()
          : false;
        return (
          <li
            key={p.probe_id}
            className="flex items-start justify-between gap-3 rounded-md border bg-card p-3"
          >
            <div className="min-w-0">
              <div className="text-sm font-medium">
                Challenge at event count{" "}
                <span className="tabular-nums">{p.target_event_count}</span>
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                nonce{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
                  {p.nonce.slice(0, 12)}…
                </code>
              </div>
              <div className="text-xs text-muted-foreground">
                issued {timeAgo(p.issued_at)} ·{" "}
                {isExpired
                  ? `expired ${timeAgo(expiresIso)}`
                  : `expires ${timeUntil(expiresIso)}`}
              </div>
            </div>
            <Badge variant={isExpired ? "destructive" : "warning"}>
              {isExpired ? "expired" : "pending"}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}
