/**
 * Reference points for the Gauntlet's accuracy numbers. A hit rate or Brier
 * score means little without something to compare it against, so the UI shows
 * what a blind guess would have scored on the same grid.
 *
 * These are display helpers only. The engine still computes every metric.
 */

/** Typical F1 grid size, used for the chance baselines. */
export const TYPICAL_GRID_SIZE = 20;

/** Chance of naming the winner by picking one driver at random. */
export function randomWinnerRate(gridSize: number = TYPICAL_GRID_SIZE): number {
  return 1 / gridSize;
}

/**
 * Multi-class Brier score of a uniform winner forecast over `gridSize` drivers.
 * Sum over drivers of (p - outcome)^2 with p = 1/N collapses to (N - 1) / N.
 * Lower is better; the engine's score is bounded by 2.
 */
export function uniformBrier(gridSize: number = TYPICAL_GRID_SIZE): number {
  return (gridSize - 1) / gridSize;
}

/** Whole rounds behind a rate, e.g. 0.25 over 24 rounds is 6. */
export function hitCount(rate: number, rounds: number): number {
  return Math.round(rate * rounds);
}

/** "6 of 24 rounds (25%)": the fraction first, the percentage as a footnote. */
export function formatHitFraction(rate: number, rounds: number): string {
  return `${hitCount(rate, rounds)} of ${rounds} (${Math.round(rate * 100)}%)`;
}

/** Whole-percent label that never rounds a real chance down to "0%". */
export function formatPercent(probability: number): string {
  if (probability > 0 && probability < 0.01) return "<1%";
  return `${Math.round(probability * 100)}%`;
}
