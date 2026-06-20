/**
 * /docs/use-cases/compliance — Compliance & audit.
 *
 * Sprint UX-5.15.F (task #846). Carved from old /docs#compliance
 * use-case section. Content preserved verbatim.
 */
export const metadata = {
  title: "Compliance & audit — Drift Engine docs",
  description:
    "GDPR, SOC 2, ISO 27001, the EU AI Act — all want tamper-evident logs of automated decisions. Drift Engine gives you that, with cryptographic signatures, without ever seeing the content.",
  alternates: { canonical: "/drift-engine/docs/use-cases/compliance" },
};

const HOW_IT_WORKS = [
  "Every event your AI processes goes through Drift Engine — hashes plus low-resolution structural signals (lengths, format flags, tool names, a salted vocabulary fingerprint), never the content.",
  "Each event is signed with a per-agent secret only you hold, and the resulting timeline is tamper-evident end to end.",
  "An auditor can pull the full history, verify it end-to-end, and confirm no event was inserted, removed or modified after the fact.",
  "Because we never store plaintext, your data residency story stays clean. The audit log lives independently of the AI vendor.",
];

export default function ComplianceUseCasePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-block rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Compliance &amp; audit
          </span>
        </div>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
          Prove what your AI did, without surrendering your data.
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          GDPR, SOC 2, ISO 27001, the EU AI Act &mdash; all want
          tamper-evident logs of automated decisions. Drift Engine gives
          you that, with cryptographic signatures, without ever seeing
          the content.
        </p>
        <p className="text-sm">
          <span className="font-medium">For:</span>{" "}
          <span className="text-muted-foreground">
            Regulated SMBs, security &amp; compliance officers.
          </span>
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          The problem
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Your auditor wants &lsquo;evidence of automated-decision
          controls&rsquo;. Your AI vendor&apos;s logs are buried inside
          their dashboard, signed by no one, mutable on their side. If
          they get hacked, your audit trail vanishes. If they go down,
          so does your evidence. You need something independent.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          How Drift Engine solves it
        </h2>
        <ol className="space-y-3">
          {HOW_IT_WORKS.map((step, i) => (
            <li
              key={i}
              className="flex gap-4 rounded-lg border bg-card p-4"
            >
              <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
                {i + 1}
              </span>
              <p className="text-sm text-muted-foreground">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Issue #53 — EU AI Act Art. 72 + Art. 12 explicit mapping */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          EU AI Act — what the law requires from you
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          The EU AI Act obligations land{" "}
          <strong>2 December 2027</strong>. Two articles are directly
          relevant to teams running AI agents in production:
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Art. 72 — Post-market monitoring
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              EU AI Act Art. 72 requires providers to actively monitor
              AI system performance post-deploy &mdash; not just document
              it. Drift Engine is that monitoring system: behavioral baseline,
              drift detection, and continuous verification that the agent
              running today is the one you deployed.
            </p>
          </div>
          <div className="rounded-lg border bg-card p-5">
            <h3 className="text-sm font-semibold tracking-tight">
              Art. 12 — Record-keeping
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Art. 12 requires automatic logging of events. Drift Engine logs
              every agent turn with cryptographic signatures &mdash; a
              tamper-evident audit trail your auditor can verify
              end-to-end, independent of the AI vendor.
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Integration
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Three lines of Python via the SDK, or one import with
            FastAPI middleware. Every request your agent handles gets
            logged automatically. LangChain callback handler, FastAPI
            middleware (one import, one <code>app.add_middleware</code>),
            or the HTTP API directly from any language &mdash; each path
            lands in the same tamper-evident log.
          </p>
          {/* HIDDEN — NOT DELETED: MCP/bot-watcher integration paths.
              These do not apply to backend agents in production.
              Restore if/when client-driven or public-bot use cases are surfaced here.
          <p className="mt-2 text-sm text-muted-foreground">
            MCP for client-driven agents (one line of config in Claude
            Code, Cursor or Claude Desktop), or our public-bot watcher
            if your AI is bot-facing (paste the bot&apos;s token, no
            code). Both paths land in the same tamper-evident log.
          </p>
          */}
        </div>
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Who else benefits
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Healthcare, fintech, government, anyone shipping LLM-driven
            workflows in regulated industries.
          </p>
        </div>
      </section>
    </main>
  );
}
