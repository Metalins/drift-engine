"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, Github, Menu, X } from "lucide-react";
import { NavLink } from "@/components/NavLink";

// gh-121 (2026-06-24): self-hosted Drift Engine ships no lab marketing. The
// repo is the public product; GitHub for the source lives under the Metalins
// org, but the only public nav targets are the product docs and the source.
const GITHUB_REPO_URL = "https://github.com/Metalins/drift-engine";

const NAV_ITEMS = [
  { href: "/drift-engine/docs", label: "Docs", icon: BookOpen },
] as const;

export function PublicNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {/* ---- Desktop nav (md+) ------------------------------------- */}
      <nav className="hidden items-center gap-1 text-sm md:flex">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
          <NavLink key={href} href={href} icon={<Icon size={14} aria-hidden />}>
            {label}
          </NavLink>
        ))}
        <a
          href={GITHUB_REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
          title="Drift Engine on GitHub"
          aria-label="Drift Engine on GitHub"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <Github size={16} aria-hidden />
        </a>
      </nav>

      {/* ---- Mobile: hamburger toggle (<md) ------------------------ */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls="mobile-nav"
        className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:hidden"
      >
        {open ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
      </button>

      {/* ---- Mobile menu panel ------------------------------------- */}
      {open && (
        <div
          id="mobile-nav"
          className="absolute inset-x-0 top-full z-50 border-b bg-background shadow-sm md:hidden"
        >
          <nav className="container mx-auto flex max-w-6xl flex-col gap-1 px-4 py-3 text-sm">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <Icon size={16} aria-hidden />
                <span>{label}</span>
              </Link>
            ))}
            <a
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Github size={16} aria-hidden />
              <span>GitHub</span>
            </a>
          </nav>
        </div>
      )}
    </>
  );
}
