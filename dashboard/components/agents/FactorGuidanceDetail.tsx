/**
 * FactorGuidanceDetail — gh-81.
 *
 * The expand that turns a one-line attention message into something Diana
 * can act on. Each warning (and a couple of informational factors) carries
 * a `learn_more` triplet from the backend; this renders it as a collapsed
 * "What does this mean?" disclosure with three short sections:
 *
 *   - What happened   — the detection in plain terms (no MVS/ICR jargon)
 *   - Is it a problem — real issue vs. something that clears with more events
 *   - What to do      — the concrete next step
 *
 * Collapsed by default so a healthy-looking panel stays calm; the detail is
 * one click away when an alert needs explaining. Native <details> keeps it
 * accessible and JS-free.
 */
import type { FactorGuidance } from "@/lib/api";

export function FactorGuidanceDetail({
  guidance,
  className,
}: {
  guidance: FactorGuidance;
  className?: string;
}) {
  return (
    <details className={`group mt-1 ${className ?? ""}`}>
      <summary className="cursor-pointer list-none text-xs font-medium text-foreground/70 underline-offset-2 hover:text-foreground hover:underline">
        <span className="group-open:hidden">What does this mean?</span>
        <span className="hidden group-open:inline">Hide details</span>
      </summary>
      <dl className="mt-2 space-y-2 border-l-2 border-foreground/15 pl-3 text-xs leading-relaxed">
        <div>
          <dt className="font-semibold text-foreground/80">What happened</dt>
          <dd className="text-foreground/70">{guidance.what}</dd>
        </div>
        <div>
          <dt className="font-semibold text-foreground/80">Is it a problem?</dt>
          <dd className="text-foreground/70">{guidance.self_resolving}</dd>
        </div>
        <div>
          <dt className="font-semibold text-foreground/80">What to do</dt>
          <dd className="text-foreground/70">{guidance.action}</dd>
        </div>
      </dl>
    </details>
  );
}
