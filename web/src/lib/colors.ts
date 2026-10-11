/**
 * One fixed color per competitor, taken from the Okabe-Ito palette, which stays
 * distinguishable under the common forms of color blindness. A model keeps the
 * same color on the reveal, the Gauntlet, and the Evidence Room.
 *
 * Color is an accent only. Every use pairs it with the competitor's name, so
 * identity never depends on hue alone.
 */

import type { CompetitorId } from "../types";

export const COMPETITOR_COLORS: Record<CompetitorId, string> = {
  you: "#f0e442",
  "m1-gbm": "#56b4e9",
  "m2-logit": "#e69f00",
  "m3-form": "#cc79a7",
  ensemble: "#009e73",
};

/** Color for a model or competitor id, or undefined for ids outside the roster. */
export function competitorColor(id: string): string | undefined {
  return (COMPETITOR_COLORS as Record<string, string>)[id];
}
