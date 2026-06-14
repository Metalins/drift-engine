/**
 * /docs/use-cases/personal — Anti-impersonation.
 *
 * Sprint UX-5.15.F (task #846). Carved from the old
 * /docs#anti-impersonation use-case section. Content preserved
 * verbatim from the UseCaseSection that lived in /docs/page.tsx;
 * inlined here per the refactor spec (no wrapper component needed
 * once the use cases each have their own route).
 */
export const metadata = {
  title: "Personal AI — anti-impersonation — Drift Engine docs",
  description:
    "Impostor AI bots on Telegram, Discord and X scam people every day. Drift Engine gives your real bot a public, cryptographic identity — and a verification page anyone can check.",
  alternates: { canonical: "/drift-engine/docs/use-cases/personal" },
};

const HOW_IT_WORKS = [
  "You connect your bot's API token in the dashboard (Telegram is live today; other public-bot platforms are roadmap). Zero code.",
  "Drift Engine signs every message it observes and posts a public verification page at metalins.com/v/your-bot. From the first event, the cryptographic identity is in place — anyone can click the page and confirm it's the real one.",
  "Once your bot has been running long enough, its behavior pattern takes shape. From then on, a clone that doesn't match how your real bot actually behaves can't earn the consistent-pattern mark — even if it copies your branding.",
  "We never see content. We only hash patterns. Your conversations stay yours.",
];

export default function PersonalUseCasePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-block rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Anti-impersonation
          </span>
        </div>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
          Your users need to know the bot is really you.
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          Impostor AI bots on Telegram, Discord and X scam people every
          day. Drift Engine gives your real bot a public, cryptographic
          identity &mdash; and a verification page anyone can check.
        </p>
        <p className="text-sm">
          <span className="font-medium">For:</span>{" "}
          <span className="text-muted-foreground">
            Creators, brands, communities running public AI bots.
          </span>
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">
          The problem
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          An impostor copies your branding, spins up a bot with a
          similar handle, and DMs your users pretending to be your
          support. They lose money, you lose trust. There&apos;s no
          current way for a regular user to tell the real one apart.
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

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Integration
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Telegram is live today. Other public-bot platforms are on
            the roadmap. The integration is paste-a-token, zero code,
            no developer required.
          </p>
        </div>
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Who else benefits
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            If your bot moves money or sensitive info &mdash; crypto
            signals, customer support, deal-closing &mdash; this
            isn&apos;t optional.
          </p>
        </div>
      </section>
    </main>
  );
}
