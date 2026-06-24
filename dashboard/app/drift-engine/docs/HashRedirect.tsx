"use client";

/**
 * Hub-page client-only redirect for legacy /docs#anchor URLs.
 *
 * Sprint UX-5.15.F (task #846). The old /docs page used 14 in-page
 * anchors. After the hub + sub-routes split, every anchor moves to a
 * dedicated URL. Outside callers (carousel link copies, blog posts,
 * older browser bookmarks) may still hold a #hash. On hub load we
 * read the hash and router.replace() to the new URL — keeps every
 * documented entry point alive.
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

const REDIRECT_MAP: Record<string, string> = {
  "what-is-metalins": "/drift-engine/docs/getting-started#what-is",
  privacy: "/drift-engine/docs/getting-started#privacy",
  integration: "/drift-engine/docs/getting-started#integration",
  "agent-to-agent": "/drift-engine/docs/use-cases/agent-to-agent",
  "verify-proof-reference": "/drift-engine/docs/reference/verify-proof",
  "webhook-payload-reference": "/drift-engine/docs/reference/webhooks",
  "anti-impersonation": "/drift-engine/docs/use-cases/personal",
  "threat-model": "/drift-engine/docs/reference/threat-model",
  "identity-tiers": "/drift-engine/docs/concepts/tiers",
  "cryptographic-identity": "/drift-engine/docs/concepts/cryptographic-identity",
  "behavioral-baseline": "/drift-engine/docs/concepts/behavioral-baseline",
  // "Pattern recognition" was merged into "Behavior pattern" (UX-5.17).
  "hash-correlation": "/drift-engine/docs/concepts/behavioral-baseline",
  "drift-detection": "/drift-engine/docs/use-cases/drift",
  "drift-detection-reference": "/drift-engine/docs/concepts/drift-detection",
  compliance: "/drift-engine/docs/use-cases/compliance",
};

export default function HashRedirect() {
  const router = useRouter();
  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.location.hash;
    if (!raw) return;
    const key = raw.replace(/^#/, "");
    const target = REDIRECT_MAP[key];
    if (target) {
      router.replace(target);
    }
  }, [router]);
  return null;
}
