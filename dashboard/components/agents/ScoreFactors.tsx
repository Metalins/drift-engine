/**
 * ScoreFactors — plain-English "why this score" panel for the
 * Identity Confidence gauge. Sprint 6.2 (2026-05-15).
 *
 * The Identity Confidence number alone is opaque — a low score could mean
 * "agent is new" (info, no action), "watcher captured one-sided traffic"
 * (action: feed it conversational data), or "memory probes failing"
 * (action: investigate). The server computes a curated list of factors in
 * `identity_engine.explain_score()` and ships them alongside the snapshot;
 * we just render them here.
 *
 * Crucially: the messages NEVER name ICR / TWC / TTM / MVS. That's the
 * proprietary algorithm — see D-PROD.18.
 */
import { CheckCircle2, Info, AlertTriangle } from "lucide-react";
import type { ScoreFactor, ScoreFactorSeverity } from "@/lib/api";
import { displayAttention } from "@/lib/display-messages";
import { FactorGuidanceDetail } from "./FactorGuidanceDetail";

interface Props {
  factors: ScoreFactor[];
  className?: string;
}

const SEVERITY_STYLES: Record<
  ScoreFactorSeverity,
  { icon: typeof Info; iconClass: string; rowClass: string }
> = {
  good: {
    icon: CheckCircle2,
    iconClass: "text-emerald-600 dark:text-emerald-400",
    rowClass: "border-emerald-500/30 bg-emerald-500/5",
  },
  info: {
    icon: Info,
    iconClass: "text-sky-600 dark:text-sky-400",
    rowClass: "border-sky-500/30 bg-sky-500/5",
  },
  warning: {
    icon: AlertTriangle,
    iconClass: "text-amber-600 dark:text-amber-400",
    rowClass: "border-amber-500/40 bg-amber-500/5",
  },
};

export function ScoreFactors({ factors, className }: Props) {
  if (!factors || factors.length === 0) {
    return null;
  }
  return (
    <div className={className}>
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Why this score?
      </h3>
      <ul className="space-y-2">
        {factors.map((f, i) => {
          const style = SEVERITY_STYLES[f.severity] ?? SEVERITY_STYLES.info;
          const Icon = style.icon;
          return (
            <li
              key={`${f.code}-${i}`}
              className={`flex gap-2 rounded-md border px-3 py-2 text-xs leading-relaxed ${style.rowClass}`}
            >
              <Icon
                size={14}
                className={`mt-0.5 shrink-0 ${style.iconClass}`}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <span className="text-foreground/90">
                  {displayAttention(f.code, f.message)}
                </span>
                {/* gh-81 — context expand when the backend ships guidance. */}
                {f.learn_more && <FactorGuidanceDetail guidance={f.learn_more} />}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
