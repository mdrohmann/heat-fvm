// Shared cold->hot diverging colormap for the heatmap and its legend, and the domain
// helper that keeps the color scale fixed across an animation instead of rescaling
// every frame (which made a room sitting at a near-uniform temperature stretch a
// ~0.1C spread across the full color range, and made no two frames comparable).

export const COLOR_STOPS: [number, [number, number, number]][] = [
  [0.0, [33, 102, 172]],
  [0.25, [146, 197, 222]],
  [0.5, [247, 247, 247]],
  [0.75, [244, 165, 130]],
  [1.0, [178, 24, 43]],
];

export function colormap(t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  for (let i = 0; i < COLOR_STOPS.length - 1; i++) {
    const [t0, c0] = COLOR_STOPS[i];
    const [t1, c1] = COLOR_STOPS[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const f = t1 === t0 ? 0 : (clamped - t0) / (t1 - t0);
      return [
        Math.round(c0[0] + f * (c1[0] - c0[0])),
        Math.round(c0[1] + f * (c1[1] - c0[1])),
        Math.round(c0[2] + f * (c1[2] - c0[2])),
      ];
    }
  }
  return COLOR_STOPS[COLOR_STOPS.length - 1][1];
}

export interface ColorDomain {
  minC: number;
  maxC: number;
}

/**
 * A fixed domain for the whole day's animation, symmetric around the thermostat
 * target so white always means "at target" and the two halves of the ramp are
 * directly comparable: blue = below target, red = above.
 *
 * Uses a percentile of the deviation rather than the raw max. The heat source is a
 * point injection into one mesh cell, so its immediate cell (and, transiently, the
 * air right next to it) can run tens of degrees above the room -- physically
 * reasonable for a radiator surface, but if the domain covered that one hot cell,
 * every other frame of the day would collapse into a thin, unreadable band near
 * white. A handful of outlier cells/moments saturate to the color extremes instead
 * of setting the scale for the whole room; measured on real output, p97 keeps room-
 * scale structure visible while still clipping the point-source hot spot.
 */
export function targetAnchoredDomain(
  temperaturesC: number[],
  targetC: number,
  percentile = 0.97,
): ColorDomain {
  const deviations = temperaturesC.map((t) => Math.abs(t - targetC)).sort((a, b) => a - b);
  const index = Math.min(deviations.length - 1, Math.floor(deviations.length * percentile));
  const robustMaxDeviation = deviations.length > 0 ? deviations[index] : 0;
  const halfWidth = Math.max(0.5, robustMaxDeviation); // floor so a flat field doesn't collapse to a point
  return { minC: targetC - halfWidth, maxC: targetC + halfWidth };
}
