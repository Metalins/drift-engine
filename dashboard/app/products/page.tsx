/**
 * /products — clean card gallery of lab products.
 *
 * Each product is a compact card: name, 1-2 line description, quick links.
 * Installation instructions and deep docs live on the product's own page.
 */
import Link from "next/link";
import { Boxes, ArrowRight, Github, BookOpen, Package } from "lucide-react";

export const metadata = {
  title: "Products — Metalins",
  description:
    "Products from the Metalins research lab. Drift Engine — behavioral fingerprinting for AI agents — is our first product.",
  alternates: { canonical: "/products" },
  openGraph: {
    title: "Products — Metalins",
    description:
      "Products from the Metalins research lab. Drift Engine — behavioral fingerprinting for AI agents — is our first product.",
    type: "website",
  },
};

const DRIFT_ENGINE_REPO_URL = "https://github.com/Metalins/drift-engine";
const DRIFT_ENGINE_PYPI_URL = "https://pypi.org/project/metalins-drift/";

const products = [
  {
    icon: Boxes,
    name: "Drift Engine",
    tagline: "Behavioral fingerprinting for AI agents",
    description:
      "Detects model swaps, drift, and prompt injection from behavioral signals alone.",
    badge: "AGPL-3.0 · Self-hosted",
    cta: { label: "Get started", href: "/drift-engine/docs/getting-started" },
    links: [
      { label: "GitHub", href: DRIFT_ENGINE_REPO_URL, external: true, icon: Github },
      { label: "Docs", href: "/drift-engine/docs/getting-started", external: false, icon: BookOpen },
      { label: "PyPI", href: DRIFT_ENGINE_PYPI_URL, external: true, icon: Package },
    ],
  },
];

export default function ProductsPage() {
  return (
    <main className="space-y-10 pb-16">
      {/* Header */}
      <section className="space-y-4 pt-6">
        <p className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Metalins · Products
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Products
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Tools that come out of the lab&apos;s research — published with open
          or commercial licenses depending on the project.
        </p>
      </section>

      {/* Card grid */}
      <section>
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" role="list">
          {products.map((product) => {
            const Icon = product.icon;
            return (
              <li key={product.name}>
                <article className="flex h-full flex-col rounded-2xl border bg-card p-6 transition-shadow hover:shadow-md">
                  {/* Icon + name */}
                  <div className="flex items-center gap-3">
                    <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <Icon size={18} aria-hidden="true" />
                    </span>
                    <div>
                      <h2 className="text-base font-semibold tracking-tight leading-tight">
                        {product.name}
                      </h2>
                      <p className="text-xs text-muted-foreground">
                        {product.tagline}
                      </p>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="mt-4 flex-1 text-sm text-muted-foreground">
                    {product.description}
                  </p>

                  {/* Quick links */}
                  <div className="mt-5 flex flex-wrap gap-2">
                    {product.links.map((link) => {
                      const LinkIcon = link.icon;
                      return link.external ? (
                        <a
                          key={link.label}
                          href={link.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
                        >
                          <LinkIcon size={12} aria-hidden="true" />
                          {link.label}
                        </a>
                      ) : (
                        <Link
                          key={link.label}
                          href={link.href}
                          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
                        >
                          <LinkIcon size={12} aria-hidden="true" />
                          {link.label}
                        </Link>
                      );
                    })}
                  </div>

                  {/* CTA */}
                  <div className="mt-4 flex items-center justify-between border-t pt-4">
                    <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {product.badge}
                    </span>
                    <Link
                      href={product.cta.href}
                      className="inline-flex items-center gap-1 text-xs font-medium text-foreground hover:underline"
                    >
                      {product.cta.label}
                      <ArrowRight size={12} aria-hidden="true" />
                    </Link>
                  </div>
                </article>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Back */}
      <p className="text-sm text-muted-foreground">
        <Link href="/" className="underline hover:text-foreground">
          ← Back to Metalins
        </Link>
      </p>
    </main>
  );
}
