/**
 * Global 404 boundary. Required by Cloudflare Pages adapter — Next's auto-
 * generated `/_not-found` route otherwise has no runtime declaration and
 * the adapter refuses to build.
 */
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="space-y-4">
      <div className="rounded-md border bg-card p-6">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you&apos;re looking for doesn&apos;t exist.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back home
        </Link>
      </div>
    </main>
  );
}
