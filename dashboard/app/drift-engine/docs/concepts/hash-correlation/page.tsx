/**
 * /docs/concepts/hash-correlation — merged into "Behavior pattern".
 *
 * UX-5.17 docs pass. The old "Pattern recognition" page and the
 * "Behavior pattern" page (/docs/concepts/behavioral-baseline) were
 * near-duplicates — the 4 fresh-eyes persona reviews all flagged it as
 * one concept split across two pages. They are now a single page at
 * /docs/concepts/behavioral-baseline. This route is kept as a
 * permanent redirect so old links, bookmarks and the legacy
 * /docs#hash-correlation anchor still resolve.
 */
import { redirect } from "next/navigation";

export default function HashCorrelationRedirect() {
  redirect("/drift-engine/docs/concepts/behavioral-baseline");
}
