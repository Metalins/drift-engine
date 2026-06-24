/**
 * Root route — redirect only.
 *
 * gh-121 (2026-06-24): the self-hosted Drift Engine dashboard is a product,
 * not the Metalins lab landing. When someone runs `docker compose up` and
 * opens `localhost:3000`, they should land on the product — the login screen
 * if they're signed out, or their dashboard if they're already in — NOT a
 * research-lab marketing page (About / Writing / Products), which belongs to
 * the hosted metalins.com site and was removed from this repo.
 *
 * There's no UI to render here: we resolve the session server-side and bounce.
 */
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth/server";

export default async function Home() {
  const user = await getCurrentUser();
  redirect(user ? "/dashboard" : "/login");
}
