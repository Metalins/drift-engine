/**
 * AgentAlert — UX-5.15.AG (2026-05-19).
 *
 * The homogeneous shell every agent-problem alert renders through.
 *
 * Before this sprint each problem type had its own layout: a severe
 * crypto/revoked issue collapsed the whole detail page; a behavioral
 * warning was a bespoke amber hero; drift and watcher errors were
 * one-off cards. Jose's rule (UX-5.15.AG): every problem an agent can
 * have must look and behave the same — a card that stacks with the
 * others, explains itself, and offers its own actions.
 *
 * `AgentAlert` is the chrome (border + severity colour + icon + title
 * + body slot). `IssueCard` renders a data-only issue (the generic
 * crypto / behavioral / revoked cases) through it. `DriftAlert` and
 * `WatcherAlert` render their interactive bodies through the SAME
 * shell, so nothing can visually drift apart.
 *
 * Severity → colour: "action" = destructive/red (you must do
 * something now), "attention" = amber (worth a look, not urgent).
 */
import Link from "next/link";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import type { AgentIssue, IssueSeverity } from "@/lib/agent-issues";
import { FactorGuidanceDetail } from "./FactorGuidanceDetail";

interface AgentAlertProps {
  severity: IssueSeverity;
  title: React.ReactNode;
  /** Overrides the per-severity default icon (e.g. WatcherAlert uses Unplug). */
  icon?: React.ReactNode;
  /** Accessible name for the section landmark. */
  ariaLabel?: string;
  children: React.ReactNode;
}

const SEVERITY_CHROME: Record<
  IssueSeverity,
  { section: string; icon: string }
> = {
  action: {
    section: "border-destructive/55 bg-destructive/10",
    icon: "text-destructive",
  },
  attention: {
    section: "border-amber-500/60 bg-amber-500/10",
    icon: "text-amber-700 dark:text-amber-400",
  },
  // UX-5.15.AM — calm informational alert (e.g. an upgrade suggestion).
  // Not a problem: blue, not amber/red.
  info: {
    section: "border-sky-500/50 bg-sky-500/10",
    icon: "text-sky-700 dark:text-sky-400",
  },
};

export function AgentAlert({
  severity,
  title,
  icon,
  ariaLabel,
  children,
}: AgentAlertProps) {
  const chrome = SEVERITY_CHROME[severity];
  const defaultIcon =
    severity === "action" ? (
      <ShieldAlert size={22} />
    ) : severity === "info" ? (
      <Info size={22} />
    ) : (
      <AlertTriangle size={22} />
    );

  return (
    <section
      className={`rounded-lg border-2 p-6 ${chrome.section}`}
      aria-label={ariaLabel}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 shrink-0 ${chrome.icon}`} aria-hidden="true">
          {icon ?? defaultIcon}
        </span>
        <div className="flex-1 space-y-3">
          <h2 className="text-base font-semibold tracking-tight text-foreground">
            {title}
          </h2>
          {children}
        </div>
      </div>
    </section>
  );
}

/**
 * IssueCard — renders a data-only AgentIssue (kind "card"): the
 * revoked, cryptographic-compromise, cryptographic-caution and
 * behavioral-warning cases. Interactive issues (drift, watcher) have
 * their own components but share the AgentAlert shell above.
 */
export function IssueCard({ issue }: { issue: AgentIssue }) {
  const paragraphs = issue.paragraphs ?? [];
  const bullets = issue.bullets ?? [];
  const actions = issue.actions ?? [];

  return (
    <AgentAlert severity={issue.severity} title={issue.title} ariaLabel={issue.title}>
      {paragraphs.map((p, i) => (
        <p key={i} className="text-sm leading-relaxed text-foreground/90">
          {p}
        </p>
      ))}

      {bullets.length > 0 && (
        <ul className="ml-5 list-disc space-y-2 text-sm text-foreground/80">
          {bullets.map((b, i) => (
            <li key={i}>
              {b.text}
              {/* gh-81 — per-bullet context expand when guidance is present. */}
              {b.guidance && <FactorGuidanceDetail guidance={b.guidance} />}
            </li>
          ))}
        </ul>
      )}

      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {actions.map((a) => (
            <Link
              key={a.href + a.label}
              href={a.href}
              className={
                a.primary
                  ? "inline-flex items-center rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90"
                  : "inline-flex items-center rounded-md border border-foreground/20 px-4 py-2 text-sm font-medium hover:bg-muted/50"
              }
            >
              {a.label}
            </Link>
          ))}
        </div>
      )}
    </AgentAlert>
  );
}
