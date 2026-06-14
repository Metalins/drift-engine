/**
 * PersonaLanding — shared layout for the 4 dedicated entry points.
 *
 * Sprint UX-5.5e (2026-05-16). One physical product, four narratives.
 * Each instance carries the persona-specific copy from
 * docs/product/MESSAGING-AND-ACQUISITION.md §1.
 *
 * Server Component (no client state). Renders:
 *   1. Hero (badge / H1 / sub / bullets / CTA)
 *   2. "How it works for you" — three steps tailored per persona
 *   3. Why this matters — short emotional body that anchors the JTBD
 *   4. Free-tier reminder + privacy bar
 *   5. Final CTA
 *
 * Routing: parent passes `signedIn` so the CTA goes to /dashboard for
 * logged-in users and /login for new visitors. The PersonaLanding
 * component itself does no Supabase calls — the page file does.
 */
import Link from "next/link";

export interface PersonaStep {
  n: string;
  title: string;
  body: string;
}

export interface PersonaLandingProps {
  badge: string;
  h1: React.ReactNode;
  sub: React.ReactNode;
  bullets: string[];
  primaryCtaLabel: string;
  ctaHref: string;
  whyTitle: string;
  whyBody: React.ReactNode;
  steps: PersonaStep[];
  trustLine: string;
  /**
   * Optional contextual link surfaced in the trust/privacy section.
   * Used by /for-engineering-teams to point evaluators at
   * /docs/concepts/availability ("What happens if Metalins goes down?"),
   * a buy-decision question for production agents (#10). Other personas
   * omit it.
   */
  trustLink?: { href: string; label: string };
  /**
   * Optional co-leading pillar rendered immediately after the hero,
   * before "How it works". Used by /for-engineering-teams (#11) to
   * surface the cryptographic audit trail / compliance story as a
   * pillar co-equal with the identity-verification framing — not a
   * footnote. Other personas omit it.
   */
  pillar?: {
    emoji: string;
    title: React.ReactNode;
    body: React.ReactNode;
  };
  /**
   * Subtext under the final-CTA heading. Defaults to the zero-code
   * framing that fits the watcher/MCP personas (Carlos, Andrea). Diana
   * (/for-engineering-teams) overrides it with the honest SDK reality —
   * "3 lines of Python" — because "No code" reads as false to an
   * engineer who knows they'll be adding a dependency, and that breaks
   * trust in the rest of the pitch (#12).
   */
  ctaSubtext?: React.ReactNode;
}

export function PersonaLanding({
  badge,
  h1,
  sub,
  bullets,
  primaryCtaLabel,
  ctaHref,
  whyTitle,
  whyBody,
  steps,
  trustLine,
  trustLink,
  pillar,
  ctaSubtext = "Magic-link signup. No code.",
}: PersonaLandingProps) {
  return (
    <main className="space-y-20 pb-16">
      {/* Hero --------------------------------------------------------- */}
      <section className="space-y-6 pt-12">
        <span className="inline-flex items-center gap-2 rounded-full border bg-muted/40 px-3 py-1 text-xs text-muted-foreground">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
          {badge}
        </span>
        <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight md:text-5xl">
          {h1}
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">{sub}</p>

        <ul className="space-y-1.5 pt-2 text-sm text-muted-foreground">
          {bullets.map((b) => (
            <li key={b} className="flex items-start gap-2">
              <span
                className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500"
                aria-hidden="true"
              />
              <span>{b}</span>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap gap-3 pt-2">
          <Link
            href={ctaHref}
            className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {primaryCtaLabel}
          </Link>
          <Link
            href="/drift-engine/docs"
            className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-accent"
          >
            How it works
          </Link>
        </div>
      </section>

      {/* Co-leading pillar ------------------------------------------- */}
      {pillar && (
        <section className="rounded-2xl border bg-card p-8 md:p-10">
          <div className="grid gap-6 md:grid-cols-[auto_1fr] md:items-center md:gap-10">
            <div className="text-5xl">{pillar.emoji}</div>
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                {pillar.title}
              </h2>
              <div className="mt-2 max-w-2xl text-muted-foreground">
                {pillar.body}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Steps -------------------------------------------------------- */}
      <section className="space-y-6">
        <h2 className="text-2xl font-semibold tracking-tight">
          How it works for you
        </h2>
        <ol className="grid gap-3 md:grid-cols-3">
          {steps.map((s) => (
            <li
              key={s.n}
              className="rounded-xl border bg-card p-5"
            >
              <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
                {s.n}
              </div>
              <div className="mt-3 font-medium">{s.title}</div>
              <p className="mt-1 text-sm text-muted-foreground">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Why this matters -------------------------------------------- */}
      <section className="rounded-2xl border bg-card p-8 md:p-10">
        <h2 className="text-2xl font-semibold tracking-tight">{whyTitle}</h2>
        <div className="mt-3 max-w-2xl text-muted-foreground">{whyBody}</div>
      </section>

      {/* Privacy ----------------------------------------------------- */}
      <section className="rounded-2xl border bg-card p-8 md:p-10">
        <div className="grid gap-6 md:grid-cols-[auto_1fr] md:items-center md:gap-10">
          <div className="text-5xl">🔒</div>
          <div>
            <h2 className="text-xl font-semibold tracking-tight">
              We never read your content.
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Each event leaves your servers as short, irreversible hashes
              plus a few low-resolution structural signals — lengths, format
              flags, the names of tools called, and a salted fingerprint of
              the output&apos;s vocabulary. Never your prompts, your
              responses, your tool arguments, or your users&apos; data.
              Those structural signals are exactly what let Metalins spot
              drift and impersonation without ever reading what your agent
              says.{" "}
              {trustLine}
            </p>
            {trustLink && (
              <p className="mt-3 text-sm">
                <Link
                  href={trustLink.href}
                  className="font-medium text-foreground hover:underline"
                >
                  {trustLink.label}
                </Link>
              </p>
            )}
          </div>
        </div>
      </section>

      {/* Final CTA --------------------------------------------------- */}
      <section className="rounded-2xl border bg-card p-10 text-center">
        <h2 className="text-3xl font-semibold tracking-tight">
          Ready in five minutes.
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-muted-foreground">
          {ctaSubtext}
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link
            href={ctaHref}
            className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {primaryCtaLabel}
          </Link>
          <Link
            href="/"
            className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-accent"
          >
            Back to home
          </Link>
        </div>
      </section>
    </main>
  );
}
