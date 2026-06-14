/**
 * CollapsedSection — UX-5.15.P / P.5.
 *
 * Wrapper used on /agents/[id] to fold secondary cards into a
 * single-line summary by default. The lifecycle doc rector §7 says:
 * "Simplificar la cara del agente cuando NO hay drift: 1 línea +
 * curva. Settings/anchors/share detrás de menús secundarios."
 *
 * Native <details> for accessibility + zero JS. The summary stays
 * keyboard-focusable and screen-reader friendly.
 *
 * Use it for state==="calma" / "baselining" — when there's nothing
 * urgent the customer needs to digest, fold the detail behind a
 * disclosure. When state==="atencion" or DriftAlert is active, the
 * caller should render the underlying card expanded directly (skip
 * this wrapper) so important signals aren't behind a click.
 */
import { ChevronRight } from "lucide-react";

interface Props {
  /** Section heading text, e.g. "Trust details". */
  title: string;
  /** One-line summary visible when collapsed, e.g. "Cryptographic
   *  identity verified · behavior consistent". */
  summary: string;
  /** Optional emerald/sky/amber/etc tone. Defaults to neutral. */
  tone?: "neutral" | "ok" | "info";
  /** Force open at mount (e.g. user has a pending probe). */
  defaultOpen?: boolean;
  children: React.ReactNode;
}

const TONE_CLASSES: Record<NonNullable<Props["tone"]>, string> = {
  neutral: "border-foreground/10",
  ok: "border-emerald-500/20",
  info: "border-sky-500/20",
};

export function CollapsedSection({
  title,
  summary,
  tone = "neutral",
  defaultOpen = false,
  children,
}: Props) {
  return (
    <details
      className={`group rounded-lg border bg-card ${TONE_CLASSES[tone]}`}
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4 hover:bg-muted/30 [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={16}
          className="shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="mt-0.5 truncate text-sm text-muted-foreground">
            {summary}
          </div>
        </div>
      </summary>
      <div className="border-t bg-background/40 p-5">{children}</div>
    </details>
  );
}
