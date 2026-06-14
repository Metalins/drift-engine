/**
 * StripNewParam — silently removes `?new=1` from the URL once the
 * agent is fully bound to an integration.
 *
 * Sprint UX-5.15.Y (2026-05-19). The wizard chain (/connect →
 * /mcp/setup → /agents/[id]?new=1) leaves the `new=1` query param
 * dangling on the detail page even after setup completed. The
 * detail page itself already gates the wizard breadcrumb and the
 * post-create picker on `integration.surface === "none"` so the
 * UI is correct — but the URL still reads `…?new=1`, which is
 * confusing if the user copies the link or refreshes later.
 *
 * This component does nothing visible: it just calls
 * `router.replace` on mount to drop the param. `scroll: false`
 * keeps the scroll position stable. We gate on `shouldStrip` from
 * the parent (server) component so the strip only happens once the
 * server confirmed the agent has an integration bound.
 *
 * Pure side-effect client component; renders `null`.
 */
"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

interface StripNewParamProps {
  /**
   * When true, this component will remove `new=1` from the current
   * URL query string. The parent should pass
   * `isJustCreated && integration.surface !== "none"` (i.e. the user
   * arrived from the wizard but the agent is already bound).
   */
  shouldStrip: boolean;
}

export function StripNewParam({ shouldStrip }: StripNewParamProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!shouldStrip) return;
    if (searchParams.get("new") !== "1") return;

    const params = new URLSearchParams(searchParams.toString());
    params.delete("new");
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [shouldStrip, pathname, searchParams, router]);

  return null;
}
