/**
 * MVSHistoryTimeline — chronological list of probes that have been responded
 * to (or expired), surfaced as a vertical timeline. Pending probes belong in
 * PendingProbesPanel.
 *
 * Each entry tells the operator: when did the challenge fire, when did the
 * agent answer, and was the proof-of-memory valid. That's the user-visible
 * face of MVS (R7.b — the AUC=1.0 clone-detection observable).
 */
import type { ProbeRow } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/utils";

interface Props {
  probes: ProbeRow[];
  emptyMessage?: string;
}

type BadgeVariant = "success" | "destructive" | "secondary" | "warning";

function statusLabel(p: ProbeRow): { variant: BadgeVariant; label: string } {
  if (p.status === "expired" || (p.expires_at && new Date(p.expires_at) < new Date() && !p.responded_at)) {
    return { variant: "destructive", label: "expired" };
  }
  if (!p.responded_at) {
    return { variant: "warning", label: "pending" };
  }
  if (p.valid === true) return { variant: "success", label: "valid" };
  if (p.valid === false) return { variant: "destructive", label: "invalid" };
  return { variant: "secondary", label: "responded" };
}

export function MVSHistoryTimeline({
  probes,
  emptyMessage = "No memory checks responded yet.",
}: Props) {
  if (!probes.length) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
  }
  return (
    <ol className="space-y-3">
      {probes.map((p) => {
        const { variant, label } = statusLabel(p);
        return (
          <li
            key={p.probe_id}
            className="flex items-start justify-between gap-3 border-b pb-3 last:border-b-0 last:pb-0"
          >
            <div className="min-w-0">
              <div className="text-sm">
                Challenge at event count{" "}
                <span className="font-medium tabular-nums">
                  {p.target_event_count}
                </span>
              </div>
              <div className="text-xs text-muted-foreground">
                issued {timeAgo(p.issued_at)}
                {p.responded_at
                  ? ` · responded ${timeAgo(p.responded_at)}`
                  : ""}
              </div>
            </div>
            <Badge variant={variant}>{label}</Badge>
          </li>
        );
      })}
    </ol>
  );
}
