/**
 * WatcherAlert — UX-5.15.AF (2026-05-19), reshelled in UX-5.15.AG.
 *
 * Pedagogical alert shown on /agents/[id] when the connected bot's
 * last poll failed (agent.watcher_state === "error").
 *
 * Why this exists: a watcher poll failure already raises a flag on the
 * dashboard and shows the translated error + Retry on the Manage bot
 * page. But the agent DETAIL page — where the customer comes to ask
 * "is my agent OK?" — said nothing. Jose's rule: anything that raises
 * an alert anywhere must also be explained on the detail page.
 *
 * UX-5.15.AG: renders through the shared <AgentAlert> shell so it's
 * visually identical to every other agent-problem card (crypto,
 * behavioral, drift, revoked). Only the icon (Unplug) and copy differ.
 *
 * Scope split with the Manage bot page (/agents/[id]/watchers): that
 * page owns the exact adapter error string + the "Retry now" button +
 * reconnect. This alert explains what a failed poll means and routes
 * there — it does not duplicate the Manage bot machinery.
 *
 * Telegram-specific copy: Telegram is the only watcher platform that
 * ships today. If another platform lands, branch the cause list on
 * the watcher's `platform`.
 */
import Link from "next/link";
import { Unplug } from "lucide-react";
import { AgentAlert } from "./AgentAlert";

interface WatcherAlertProps {
  agentId: string;
  agentName: string;
}

const CAUSES = [
  "The bot token was regenerated or revoked in @BotFather — the old token stops working the moment a new one is issued.",
  "The bot was deleted, or blocked from the chats it was watching.",
  "Telegram's API was briefly unreachable — these usually clear on their own.",
  "A network hiccup between Metalins and Telegram.",
];

export function WatcherAlert({ agentId, agentName }: WatcherAlertProps) {
  return (
    <AgentAlert
      severity="attention"
      icon={<Unplug size={22} />}
      ariaLabel="Bot connection problem"
      title={
        <>
          Metalins can&apos;t reach{" "}
          <span className="font-bold">{agentName}</span>&apos;s bot
        </>
      }
    >
      <p className="text-sm leading-relaxed text-foreground/90">
        Its last poll failed, so identity tracking is paused — no new
        activity is being recorded until the connection recovers.
        Everything already verified stays valid. This usually comes down
        to one of these:
      </p>

      <ul className="ml-5 list-disc space-y-1 text-sm text-foreground/80">
        {CAUSES.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <p className="pt-1 text-sm text-foreground/90">
        Metalins keeps retrying automatically in the background. Open the
        bot connection to see the exact error, retry right now, or
        reconnect with a fresh token.
      </p>

      <div className="flex flex-wrap gap-2 pt-1">
        <Link
          href={`/agents/${encodeURIComponent(agentId)}/watchers`}
          className="inline-flex items-center rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90"
        >
          Open bot connection →
        </Link>
      </div>
    </AgentAlert>
  );
}
