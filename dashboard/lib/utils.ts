import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Combine class names with Tailwind merge — shadcn/ui convention.
 * Lets you do `cn("text-red-500", isActive && "text-blue-500")` and the
 * later class wins for the same Tailwind axis (here, text color).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Coerce a server ISO string to an absolute timestamp.
 *
 * Defense for Bug-andrea-1: the FastAPI server has historically called
 * `.isoformat()` on naive UTC datetimes, producing strings with no
 * timezone suffix (e.g. "2026-05-17T22:00:00.123456"). Plain
 * `new Date(s)` then parses those as LOCAL time, which for a user
 * 3h west of UTC reads as "created -10800s ago" the moment the row
 * was minted. The backend `_iso_utc` helper now adds `Z` to every
 * outgoing timestamp, but old API responses and any future surface
 * that forgets the helper would still break this. So we also defend
 * here: if the string lacks both `Z` and a +HH:MM / -HH:MM offset,
 * treat it as UTC explicitly.
 */
function _parseServerISO(iso: string): number {
  const hasZ = iso.endsWith("Z");
  const hasOffset =
    iso.length >= 6 &&
    (iso[iso.length - 6] === "+" || iso[iso.length - 6] === "-") &&
    iso[iso.length - 3] === ":";
  const safe = hasZ || hasOffset ? iso : iso + "Z";
  return new Date(safe).getTime();
}

/** Format an ISO timestamp as "X seconds/minutes/hours/days ago". */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = _parseServerISO(iso);
  const now = Date.now();
  const seconds = Math.floor((now - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/**
 * Format an ISO timestamp as "in Xs/Xm/Xh/Xd" if it's in the future, or
 * fall back to "X ago" via {@link timeAgo} when it's already past. Useful
 * for deadlines like probe `expires_at` that flip from future to past
 * during the lifecycle of a probe.
 */
export function timeUntil(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = _parseServerISO(iso);
  const now = Date.now();
  const secondsAhead = Math.floor((then - now) / 1000);
  if (secondsAhead <= 0) return timeAgo(iso);
  if (secondsAhead < 60) return `in ${secondsAhead}s`;
  const minutes = Math.floor(secondsAhead / 60);
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  const days = Math.floor(hours / 24);
  return `in ${days}d`;
}

/** Format confidence (0-1) as percentage with sensible precision. */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** Format an observable that may be null with sensible precision. */
export function formatObservable(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}
