/**
 * ConfidenceGauge — half-circle SVG gauge showing identity_confidence in 0-1.
 *
 * Color zones (matches the UX we calibrated with τ=100, D-PROD.12):
 *   0.0 – 0.3 → red    (low / new agent)
 *   0.3 – 0.7 → amber  (growing)
 *   0.7 – 1.0 → green  (high confidence)
 *
 * Renders `—` when value is null so we don't lie about state on fresh agents.
 */
import { cn } from "@/lib/utils";

interface Props {
  value: number | null;
  size?: number;
  className?: string;
}

const RADIUS = 80;
const STROKE = 18;
const NORMALIZED_RADIUS = RADIUS - STROKE / 2;
// Half-circle arc length: π · r
const ARC_LENGTH = Math.PI * NORMALIZED_RADIUS;

function zoneStrokeClass(v: number): string {
  if (v >= 0.7) return "stroke-emerald-500";
  if (v >= 0.3) return "stroke-amber-500";
  return "stroke-red-500";
}

function zoneLabel(v: number): string {
  if (v >= 0.7) return "high";
  if (v >= 0.3) return "growing";
  return "low";
}

export function ConfidenceGauge({ value, size = 200, className }: Props) {
  const clamped = value === null ? 0 : Math.min(1, Math.max(0, value));
  const dashOffset = ARC_LENGTH * (1 - clamped);

  // Arc path: from (STROKE/2, RADIUS) to (2*RADIUS - STROKE/2, RADIUS),
  // sweeping over the top half of the circle.
  const arcPath = `M ${STROKE / 2} ${RADIUS} A ${NORMALIZED_RADIUS} ${NORMALIZED_RADIUS} 0 0 1 ${
    RADIUS * 2 - STROKE / 2
  } ${RADIUS}`;

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg
        width={size}
        height={size / 2 + STROKE}
        viewBox={`0 0 ${RADIUS * 2} ${RADIUS + STROKE}`}
        className="overflow-visible"
        aria-label="Identity confidence gauge"
        role="img"
      >
        <path
          d={arcPath}
          fill="none"
          className="stroke-muted"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        {value !== null && (
          <path
            d={arcPath}
            fill="none"
            className={zoneStrokeClass(clamped)}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={ARC_LENGTH}
            strokeDashoffset={dashOffset}
          />
        )}
      </svg>
      <div className="mt-2 text-center">
        <div className="text-4xl font-semibold tabular-nums">
          {value === null ? "—" : `${(clamped * 100).toFixed(0)}%`}
        </div>
        <div className="text-xs text-muted-foreground">
          {value === null ? "no data" : `identity confidence — ${zoneLabel(clamped)}`}
        </div>
      </div>
    </div>
  );
}
