import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Writing — Metalins",
  description:
    "Research notes, papers, and ideas from the Metalins lab.",
};

const POSTS = [
  {
    slug: "kappa-identity-behavioral-fingerprinting",
    title: "κ-Identity: Behavioral Fingerprinting for AI Agents",
    date: "June 15, 2026",
    description:
      "A formal framework for continuous identity verification of AI agents using behavioral fingerprinting. Introduces the κ-engine — a statistical baseline learner that detects model swaps, drift, and prompt injection without reading prompts or outputs.",
    doi: "10.5281/zenodo.20693202",
    doiUrl: "https://doi.org/10.5281/zenodo.20693202",
    href: "/writing/kappa-identity-behavioral-fingerprinting",
    tags: ["paper", "behavioral-fingerprinting", "ai-agents"],
  },
];

export default function WritingPage() {
  return (
    <main className="mx-auto max-w-2xl py-12">
      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight">Writing</h1>
        <p className="mt-2 text-muted-foreground">
          Research notes, papers, and ideas from the lab.
        </p>
      </header>

      <ul className="space-y-8">
        {POSTS.map((post) => (
          <li key={post.slug} className="border-b pb-8 last:border-0">
            <article>
              <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                <time>{post.date}</time>
                {post.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <h2 className="text-xl font-semibold leading-snug">
                {post.title}
              </h2>
              <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                {post.description}
              </p>
              {post.href && (
                <Link
                  href={post.href}
                  className="mt-3 inline-block text-sm font-medium underline hover:no-underline"
                >
                  Read →
                </Link>
              )}
            </article>
          </li>
        ))}
      </ul>
    </main>
  );
}
