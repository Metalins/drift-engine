/**
 * Footer — global, rendered on every page by the root layout.
 */
import Link from "next/link";

export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="mt-8 border-t">
      <div className="container mx-auto max-w-6xl px-4 py-8 text-sm text-muted-foreground">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          {/* Brand */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.svg" alt="" className="h-5 w-5" />
              <span className="font-medium text-foreground">Metalins</span>
              <span>&copy; {year}</span>
            </div>
            <p className="text-xs">Independent research lab.</p>
          </div>

          {/* Links */}
          <div className="flex flex-col gap-3 sm:items-end">
            {/* Social + contact */}
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              <a
                href="https://github.com/Metalins"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                GitHub
              </a>
              <a
                href="https://x.com/metalinslabs"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                X
              </a>
              <a
                href="https://www.linkedin.com/company/metalins"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                LinkedIn
              </a>
              <a
                href="mailto:support@metalins.com"
                className="hover:text-foreground"
              >
                support@metalins.com
              </a>
            </div>
            {/* Legal */}
            <div className="flex gap-4 text-xs">
              <Link href="/terms" className="hover:text-foreground">
                Terms
              </Link>
              <Link href="/privacy" className="hover:text-foreground">
                Privacy
              </Link>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
