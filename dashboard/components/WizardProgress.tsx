/**
 * WizardProgress — 4-step bar shown across the onboarding journey.
 *
 * Sprint UX-5.10-9 (#668). The "Step 1 of 4" pill from /agents/new
 * was disappearing once the user clicked Create — they'd land on
 * the agent detail with no sense of "where am I in the flow". This
 * component is rendered at the top of each wizard step page when
 * the URL carries `?new=1`, so the journey from name → connect →
 * verify stays visible end-to-end.
 *
 * Steps:
 *   1. Basics      — /agents/new (three sub-steps: purpose → behavior → name)
 *   2. Pick path   — /agents/[id]/connect?new=1 (SDK / Bot / MCP picker, UX-5.15.S)
 *   3. Setup       — /agents/[id]/mcp?new=1 or /agents/[id]/watchers?new=1
 *   4. Verify      — back at /agents/[id]?new=1 with event_count > 0
 *
 * Sprint UX-5.15.M (Jose feedback) — step 1 was originally just "Name"
 * but the multi-step wizard at /agents/new now collects purpose +
 * behavior + name. "Name" undersold what step 1 was, so the label is
 * "Basics" — covers the whole what-and-why-and-name block.
 *
 * Sprint UX-5.15.S — step 2 was "Connect" but it landed on the agent
 * detail page (which is a "no events yet" empty state) and let the
 * user fish around for surface buttons. New step 2 is the explicit
 * surface picker at /connect, so "Pick path" is the truthful label.
 *
 * Server Component — pure visual, no client state.
 */

const STEPS = [
  { n: 1, label: "Basics" },
  { n: 2, label: "Pick path" },
  { n: 3, label: "Setup" },
  { n: 4, label: "Verify" },
];

interface Props {
  currentStep: 1 | 2 | 3 | 4;
}

export function WizardProgress({ currentStep }: Props) {
  return (
    <nav
      aria-label="Onboarding progress"
      className="flex items-center gap-2 text-xs"
    >
      {STEPS.map((step, idx) => {
        const isCurrent = step.n === currentStep;
        const isComplete = step.n < currentStep;
        const dotStyle = isCurrent
          ? "bg-emerald-500 text-white"
          : isComplete
            ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-400"
            : "bg-muted text-muted-foreground";
        const labelStyle = isCurrent
          ? "font-semibold text-foreground"
          : isComplete
            ? "text-muted-foreground"
            : "text-muted-foreground/60";
        return (
          <span key={step.n} className="flex items-center gap-2">
            <span
              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${dotStyle}`}
              aria-current={isCurrent ? "step" : undefined}
            >
              {isComplete ? "✓" : step.n}
            </span>
            <span className={`uppercase tracking-wider ${labelStyle}`}>
              {step.label}
            </span>
            {idx < STEPS.length - 1 && (
              <span
                className={`h-px w-6 ${isComplete ? "bg-emerald-500/40" : "bg-muted-foreground/20"}`}
                aria-hidden="true"
              />
            )}
          </span>
        );
      })}
    </nav>
  );
}
