/**
 * /docs/concepts/integration-lifecycle — UX-5.15.P / D-PROD.25.
 *
 * Customer-facing version of docs/product/INTEGRATION-LIFECYCLE.md.
 * The internal doc has the full mechanism / moat / anti-receta detail;
 * this page is plain English for Andrea: what happens when she
 * pauses, resumes, resets baseline, or removes — and why her agent
 * changing isn't a bug.
 */
export const metadata = {
  title: "Integration lifecycle — Drift Engine docs",
  description:
    "Pause, resume, reset behavior baseline, remove. What each one does, what stays, and why your agent can change without breaking.",
  alternates: { canonical: "/drift-engine/docs/concepts/integration-lifecycle" },
};

export default function IntegrationLifecyclePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          What happens when you pause, resume, or reset
        </h1>
      </header>

      <section className="space-y-5">
        <p className="max-w-3xl text-lg text-muted-foreground">
          Your agent can change. You compact the conversation, switch
          projects, move machines, or just take a break and come back.
          Drift Engine notices, and asks you if it was expected. Below is
          what each lifecycle action actually does &mdash; and what
          stays put no matter what.
        </p>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          The four actions
        </h2>

        <div className="space-y-4">
          <article className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Pause monitoring
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Drift Engine stops accepting new events for this agent. No
              changes to your codebase. Event history is preserved.
              You&apos;d use this if your API key got exposed and you
              need to freeze right now, or if you&apos;re parking the
              project for a while.
            </p>
          </article>

          <article className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Resume monitoring
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Drift Engine starts accepting events again. As soon as your
              agent sends events, monitoring picks up where it left
              off. If the behavior post-pause is different enough from
              before, we show you a drift alert and ask what happened.
            </p>
          </article>

          <article className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Reset behavior baseline
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              You&apos;re telling Drift Engine the new behavior is the new
              normal. We discard the pattern we had learned and start
              learning again from this point. Your past events are
              <em> not </em> deleted &mdash; they stay archived as
              auditable evidence. Use this when you compacted, started
              a new project, switched machines, or anything else
              legitimate that made your agent look different. The
              button only appears when a drift alert is active.
            </p>
          </article>

          <article className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Remove agent
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              The full delete. The agent record and event history are
              removed. We show you exactly what to remove from your
              integration before you confirm, so you don&apos;t end up
              with a ghost agent sending events to nowhere.
            </p>
          </article>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          What stays put, no matter what
        </h2>
        <ul className="ml-5 list-disc space-y-2 text-sm text-muted-foreground">
          <li>
            <span className="text-foreground">Your event history.</span>{" "}
            Pause, resume, or reset baseline all preserve every event
            you&apos;ve logged. Only Remove agent erases them.
          </li>
          <li>
            <span className="text-foreground">Your code.</span>{" "}
            Pause and Resume happen entirely on our side. We never
            touch your codebase or your running deployment.
          </li>
          <li>
            <span className="text-foreground">
              Your control over &quot;is this the new normal?&quot;
            </span>{" "}
            Only you, signed in to the dashboard, can accept a behavior
            change as the new baseline. Anyone who happens to be
            holding your API key can&apos;t do it on your behalf.
            That&apos;s the point.
          </li>
        </ul>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Common situations
        </h2>
        <div className="space-y-3 text-sm">
          <p className="max-w-3xl text-muted-foreground">
            <span className="font-medium text-foreground">
              You compacted your agent&apos;s context window.
            </span>{" "}
            Behavior dips for a few events. You see the drift alert,
            click &quot;Yes, this is the new normal,&quot; and the
            score resumes from there.
          </p>
          <p className="max-w-3xl text-muted-foreground">
            <span className="font-medium text-foreground">
              You re-platformed your agent onto a new framework.
            </span>{" "}
            Drift alert appears (the behavior is different). Accept it
            and the new phase starts learning.
          </p>
          <p className="max-w-3xl text-muted-foreground">
            <span className="font-medium text-foreground">
              You redeployed your agent with the same API key.
            </span>{" "}
            If your usage pattern is similar, you won&apos;t see
            anything &mdash; identity continues seamlessly. If it
            looks different, we ask.
          </p>
          <p className="max-w-3xl text-muted-foreground">
            <span className="font-medium text-foreground">
              You suspect someone else is using your agent.
            </span>{" "}
            You see the drift alert. Click &quot;No, I didn&apos;t
            expect this&quot;. The score stays low, evidence stays
            preserved, and you can pause monitoring to stop new
            events while you investigate.
          </p>
        </div>
      </section>

      <section className="rounded-2xl border bg-card p-6 text-sm">
        <h2 className="font-semibold tracking-tight text-foreground">
          The promise in one sentence
        </h2>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          Your agent can change. We detect when it does and ask you.
          You decide if it was expected. That&apos;s it.
        </p>
      </section>
    </main>
  );
}
