import { COLOR_STOPS, type ColorDomain } from "@/lib/colormap";

interface ColorBarProps {
  domain: ColorDomain;
  targetC: number;
}

export function ColorBar({ domain, targetC }: ColorBarProps) {
  const gradient = COLOR_STOPS.map(([t, [r, g, b]]) => `rgb(${r} ${g} ${b}) ${t * 100}%`).join(", ");
  const targetPositionPct =
    ((targetC - domain.minC) / (domain.maxC - domain.minC || 1)) * 100;

  return (
    <div className="flex flex-col gap-1 text-xs text-zinc-500">
      <div
        className="relative h-3 w-full rounded"
        style={{ background: `linear-gradient(to right, ${gradient})` }}
      >
        {targetPositionPct >= 0 && targetPositionPct <= 100 && (
          <div
            className="absolute top-0 h-full w-px bg-zinc-900 dark:bg-zinc-100"
            style={{ left: `${targetPositionPct}%` }}
            title={`target: ${targetC.toFixed(1)}°C`}
          />
        )}
      </div>
      <div className="flex justify-between">
        <span>{domain.minC.toFixed(1)}°C</span>
        <span>target {targetC.toFixed(1)}°C</span>
        <span>{domain.maxC.toFixed(1)}°C</span>
      </div>
    </div>
  );
}
