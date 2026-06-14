/**
 * Permanent redirect — Sprint 4.10, mapping refreshed in Sprint UX-5.15.F
 * (task #846).
 *
 * Use-case content lives on dedicated /docs/use-cases/<group>/ routes
 * now; the prior /docs#<slug> anchor mapping is obsolete. The two
 * legacy slugs (anti-impersonation, drift-detection) keep working by
 * forwarding to their new homes (personal, drift). The two slugs whose
 * name didn't change (compliance, agent-to-agent) just go to the new
 * sub-route. Anything else falls through to the hub.
 */
import { redirect, permanentRedirect } from "next/navigation";

const SLUG_TO_URL: Record<string, string> = {
  "anti-impersonation": "/drift-engine/docs/use-cases/personal",
  "drift-detection": "/drift-engine/docs/use-cases/drift",
  compliance: "/drift-engine/docs/use-cases/compliance",
  "agent-to-agent": "/drift-engine/docs/use-cases/agent-to-agent",
};

export default async function RedirectPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const target = SLUG_TO_URL[slug];
  if (target) {
    permanentRedirect(target);
  }
  redirect("/drift-engine/docs");
}
