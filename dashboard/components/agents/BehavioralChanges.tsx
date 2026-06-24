/**
 * BehavioralChanges — #65 (κ-engine V2 drift timeline).
 *
 * Renders the agent's history of DRIFT_DETECTED events (the rows the
 * #64 alerts pipeline persists in `drift_events`). This is the
 * read-only, historical counterpart to the interactive <DriftAlert>:
 * DriftAlert is the "your agent changed — is this expected?" prompt for
 * the CURRENT drift state; this timeline is the durable record of every
 * behavioral change the engine has flagged, newest first.
 *
 * When there are no events the section reads "Behavior consistent" — the
 * calm-UX default. The engine stays content-blind, so every value here
 * is a structural summary (a length, a latency, a distribution), never
 * raw input/output.
 *
 * D-PROD.18: customer copy never names the internal tests (ks_2samp,
 * Wasserstein, TVD, Hamming). We humanize the feature name and render
 * the drift score as a plain percentage.
 *
 * Server component — pure presentation over data the page already
 * fetched. No client JS.
 */
import { timeAgo } from "@/lib/utils";
import type { DriftEventRow } from "@/lib/api";

interface Props {
  events: DriftEventRow[];
}

/**
 * Humanize an engine feature name into customer copy. Mirrors the
 * server-side `email_delivery.feature_label` so the dashboard and the
 * email agree on wording. Unknown features fall back to a de-snaked
 * version of the raw name (never the raw `snake_case`).
 */
const FEATURE_LABELS: Record<string, string> = {
  output_length_chars: "response length",
  output_length_tokens: "response length",
  input_length_chars: "prompt length",
  sentence_count_output: "response structure",
  mean_sentence_length_output: "sentence length",
  latency_ms: "response latency",
  had_code_block: "code formatting",
  had_list: "list formatting",
  had_markdown: "markdown formatting",
  error_class: "error pattern",
  tool_calls: "tool usage",
  tool_bigrams: "tool sequencing",
  token_bag_lsh: "wording pattern",
};

export function featureLabel(feature: string | null | undefined): string {
  if (!feature) return "behavior";
  return FEATURE_LABELS[feature] ?? feature.replace(/_/g, " ");
}

function scorePct(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

export function BehavioralChanges({ events }: Props) {
  if (events.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span
          aria-hidden
          className="inline-block h-2 w-2 rounded-full bg-emerald-500"
        />
        Behavior consistent — no changes detected against the learned
        baseline.
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {events.map((ev) => {
        const acknowledged = ev.acknowledged_at !== null;
        return (
          <li
            key={ev.id}
            className="rounded-md border bg-background/40 p-3 text-sm"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="font-medium text-foreground">
                {featureLabel(ev.dominant_feature)} changed
              </div>
              <div className="text-xs text-muted-foreground">
                {ev.detected_at ? timeAgo(ev.detected_at) : "—"}
              </div>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>Change strength {scorePct(ev.drift_score)}</span>
              {ev.baseline_value !== null && ev.current_value !== null && (
                <span>
                  was{" "}
                  <span className="font-medium text-foreground">
                    {ev.baseline_value}
                  </span>{" "}
                  → now{" "}
                  <span className="font-medium text-foreground">
                    {ev.current_value}
                  </span>
                </span>
              )}
              {acknowledged && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">
                  marked as expected
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
