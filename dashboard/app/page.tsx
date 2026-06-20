/**
 * Landing — public.
 *
 * gh-115 (2026-06-15): pulled the landing up to the lab altitude. The home
 * had drifted back into a product page — ~70% of it pitched Drift Engine
 * (threat model, privacy model, agent-to-agent, a full install card, a
 * self-hosting section). All of that already lives on /products and
 * /drift-engine/docs, so it was removed here. The home now reads as the
 * front door of the organization:
 *
 *   Hero → About → Writing → Products (pointer).
 *
 *   • Hero keeps the lab mission ("We explore, build, and publish") and drops
 *     the product subtitle; the broader lab paragraph and CTAs stay.
 *   • New "About" (#about) section positions Metalins as an independent
 *     research lab whose problems — not a roadmap — decide the work.
 *   • "Writing" (#research) reframes from "the research behind the product"
 *     into an index of the lab's published work; the κ-Identity paper is the
 *     first entry, with room for future topics.
 *   • "Products" (#products) is now a one-line pointer to /products, where the
 *     full Drift Engine card lives. No duplication.
 *
 * Earlier history:
 *   gh-100 (2026-06-14): restructured from a SaaS-style product landing into
 *   the front door of a research lab (but kept the product-heavy body).
 *   gh-90 (2026-06-14): first pass repositioning from SaaS product to
 *   research organization.
 *
 * NOTE: anti-indexing (ALLOW_INDEX / robots.ts) is handled separately in
 * gh-93 — not touched here.
 */
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth/server";

export const metadata = {
  title: "Metalins — Independent Research Lab",
  description:
    "Metalins is an independent research lab. We explore, build, and publish. Drift Engine — open-source behavioral fingerprinting for AI agents — is our first product.",
};

const GITHUB_ORG_URL = "https://github.com/Metalins";

export default async function LandingPage() {
  const user = await getCurrentUser();

  return (
    <main className="space-y-20 pb-16">
      {/* ----- Hero ---------------------------------------------------- */}
      <section className="grid items-center gap-12 pt-12 md:grid-cols-[1.2fr_1fr]">
        <div className="space-y-6">
          <p className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
            Metalins · Independent Research Lab
          </p>
          <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
            We explore, build, and{" "}
            <span className="text-muted-foreground">publish.</span>
          </h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            Metalins is an independent research lab. We work on what&apos;s
            genuinely interesting &mdash; not what a roadmap says. When
            something is worth building, we build it. Our first area is{" "}
            <em>behavioral verification of AI agents</em>, and the first thing
            out of it is Drift Engine.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/products"
              className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Explore our products
            </Link>
            <a
              href={GITHUB_ORG_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-accent"
            >
              View on GitHub
            </a>
            <a
              href="#research"
              className="rounded-md border px-5 py-2.5 text-sm font-medium hover:bg-accent"
            >
              Read our writing
            </a>
          </div>
          {user && (
            <p className="pt-2 text-xs text-muted-foreground">
              <Link href="/dashboard" className="underline hover:text-foreground">
                Go to your dashboard →
              </Link>
            </p>
          )}
        </div>
        <div className="flex items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.svg"
            alt="The Metalins character — a small grey figure with two large eyes"
            className="h-64 w-64 drop-shadow-xl md:h-80 md:w-80"
          />
        </div>
      </section>

      {/* ----- About -------------------------------------------------
          gh-115 (2026-06-15): the landing now speaks for the lab, not the
          product. Drift Engine's pitch, threat model, privacy model, and
          agent-to-agent use case all live on /products and the docs — they
          were removed from the home so the front door positions Metalins as
          an organization that happens to have a first product, not a SaaS.
      -------------------------------------------------------------- */}
      <section id="about" className="scroll-mt-20 space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          About
        </h2>
        <p className="text-muted-foreground">
          Metalins is an independent research lab. The questions decide what we
          work on &mdash; not a roadmap, not a market. Sometimes that leads to
          a product. Sometimes to a paper. Sometimes to a dead end that was
          still worth exploring.
        </p>
        <ul className="grid gap-2 text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">We explore.</span>{" "}
            Problems that are genuinely unsolved, wherever they lead.
          </li>
          <li>
            <span className="font-medium text-foreground">We build.</span>{" "}
            When the research is solid, we turn it into something people can
            actually run.
          </li>
          <li>
            <span className="font-medium text-foreground">We publish.</span>{" "}
            When there&apos;s something worth saying, we say it.
          </li>
        </ul>
      </section>

      {/* ----- Writing / Research ------------------------------------- */}
      <section id="research" className="scroll-mt-20 space-y-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Writing
          </h2>
          <p className="mt-3 text-muted-foreground">
            Published work from the lab. Methods, results, and the ideas
            behind what we build. The topics won&apos;t stay in one field.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col rounded-xl border bg-card p-6">
            <h3 className="text-base font-semibold">
              κ-Identity: Behavioral Fingerprinting for Continuous Verification
              of LLM Agents
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Metalins Research · 2026
            </p>
            <p className="mt-3 text-sm text-muted-foreground">
              A foundational write-up of the approach: why cryptographic hashes
              alone fail for probabilistic AI agents, the distributional methods
              (Kolmogorov&ndash;Smirnov, Wasserstein, chi-squared, LSH) behind
              the behavioral engine, and κ-Proofs as a portable attestation any
              third party can verify offline.
            </p>
            <p className="mt-3 text-xs text-muted-foreground">
              DOI:{" "}
              <a
                href="https://doi.org/10.5281/zenodo.20693202"
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-foreground underline hover:no-underline"
              >
                10.5281/zenodo.20693202
              </a>
            </p>
            <p className="mt-4 text-sm font-medium">
              <a
                href="https://doi.org/10.5281/zenodo.20693202"
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground underline hover:no-underline"
              >
                Read paper →
              </a>
            </p>
          </div>
        </div>
      </section>

      {/* ----- Products ----------------------------------------------
          Minimal pointer only — the full product gallery lives at
          /products. The home no longer duplicates it.
      -------------------------------------------------------------- */}
      <section id="products" className="scroll-mt-20 space-y-3">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Products
        </h2>
        <p className="text-muted-foreground">
          Our first product is{" "}
          <Link href="/products" className="text-foreground underline hover:no-underline">
            Drift Engine
          </Link>{" "}
          &mdash; open-source behavioral fingerprinting for AI agents.
        </p>
      </section>
    </main>
  );
}
