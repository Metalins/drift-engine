"use client";

/**
 * UseCaseCarousel — landing carousel that shows one use case at a time,
 * auto-advances every 6s, supports prev/next arrows + dot indicators, and
 * pauses on hover (so the user has time to read whichever card they're
 * pointing at). Sprint 5 (2026-05-14) rewrite of the prior scroll-snap
 * version (which showed multiple cards at once and felt busy).
 *
 * The wrapping card itself is a <Link> to the matching /docs/use-cases/<group>/
 * route (mapped via slugToUseCaseUrl below — refreshed in Sprint UX-5.15.F
 * when /docs was split into hub + sub-routes). Arrow / dot controls
 * stopPropagation so they don't trigger the underlying link.
 *
 * Manual navigation (arrow / dot) ALSO re-arms the timer (useEffect dep on
 * `index`), so the user gets a full interval after clicking before the next
 * auto-advance.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface CarouselCase {
  slug: string;
  tag: string;
  title: string;
  body: string;
  audience: string;
}

interface Props {
  cases: CarouselCase[];
  /** Auto-advance interval in ms. 0 disables auto-advance. */
  intervalMs?: number;
}

/**
 * Map a carousel slug to the corresponding /docs/use-cases/<group>/ URL.
 * Mirrors the new hub + sub-routes layout introduced in UX-5.15.F.
 * Falls back to the docs hub if a slug doesn't have a dedicated page.
 */
function slugToUseCaseUrl(slug: string): string {
  switch (slug) {
    case "anti-impersonation":
      return "/drift-engine/docs/use-cases/personal";
    case "drift-detection":
      return "/drift-engine/docs/use-cases/drift";
    case "compliance":
      return "/drift-engine/docs/use-cases/compliance";
    case "agent-to-agent":
      return "/drift-engine/docs/use-cases/agent-to-agent";
    default:
      return "/drift-engine/docs";
  }
}

export function UseCaseCarousel({ cases, intervalMs = 6000 }: Props) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused || intervalMs <= 0) return;
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % cases.length);
    }, intervalMs);
    return () => clearInterval(id);
  }, [paused, intervalMs, cases.length, index]);

  function go(delta: number, e?: React.MouseEvent) {
    e?.preventDefault();
    e?.stopPropagation();
    setIndex((i) => (i + delta + cases.length) % cases.length);
  }

  function goTo(i: number, e?: React.MouseEvent) {
    e?.preventDefault();
    e?.stopPropagation();
    setIndex(i);
  }

  const current = cases[index];

  return (
    <div
      className="relative"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <Link
        href={slugToUseCaseUrl(current.slug)}
        aria-live="polite"
        className="group block rounded-2xl border bg-card p-6 transition-colors hover:border-foreground/40 sm:p-8 md:p-10"
      >
        <span className="inline-flex rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {current.tag}
        </span>
        <h3 className="mt-4 text-xl font-semibold leading-tight tracking-tight sm:text-2xl md:text-3xl">
          {current.title}
        </h3>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          {current.body}
        </p>
        <p className="mt-3 text-xs italic text-muted-foreground">
          For: {current.audience}
        </p>
        <p className="mt-4 text-sm font-medium text-foreground group-hover:underline">
          Read the full story →
        </p>
      </Link>

      {/* Prev / next arrows. Absolutely positioned over the card. */}
      <button
        type="button"
        onClick={(e) => go(-1, e)}
        aria-label="Previous use case"
        className="absolute left-2 top-1/2 hidden -translate-y-1/2 rounded-full border bg-background p-2 shadow-sm transition-colors hover:bg-accent md:flex"
      >
        <ChevronLeft size={20} />
      </button>
      <button
        type="button"
        onClick={(e) => go(1, e)}
        aria-label="Next use case"
        className="absolute right-2 top-1/2 hidden -translate-y-1/2 rounded-full border bg-background p-2 shadow-sm transition-colors hover:bg-accent md:flex"
      >
        <ChevronRight size={20} />
      </button>

      {/* Dot indicators + mobile arrows */}
      <div className="mt-4 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={(e) => go(-1, e)}
          aria-label="Previous use case"
          className="rounded-full border p-1.5 transition-colors hover:bg-accent md:hidden"
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex gap-2">
          {cases.map((c, i) => (
            <button
              key={c.slug}
              type="button"
              onClick={(e) => goTo(i, e)}
              aria-label={`Go to ${c.tag}`}
              aria-current={i === index}
              className={`h-1.5 rounded-full transition-all ${
                i === index
                  ? "w-8 bg-foreground"
                  : "w-2 bg-muted hover:bg-muted-foreground/40"
              }`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={(e) => go(1, e)}
          aria-label="Next use case"
          className="rounded-full border p-1.5 transition-colors hover:bg-accent md:hidden"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
