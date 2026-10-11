/**
 * "If this race ran 20 times" — a countable view of a win distribution.
 *
 * People read "6 of 20" more accurately than "31%", and an upset reads as the
 * model working rather than failing when the favorite visibly loses most
 * replays. This module turns a probability distribution into whole-dot counts.
 */

export const REPLAY_RUNS = 20;

export interface ReplayGroup {
  driverId: string;
  /** Dots this driver gets out of REPLAY_RUNS. */
  dots: number;
}

export interface ReplayStrip {
  /** Named drivers, most likely first, each with at least one dot. */
  groups: ReplayGroup[];
  /**
   * Every driver's dot count, named or not (0 for a long shot). Lets the UI say
   * where a driver fell even when they are folded into "others".
   */
  allocation: Record<string, number>;
  /** Dots left over for everyone not named. */
  otherDots: number;
  runs: number;
}

/**
 * Largest-remainder apportionment so the dots always sum to exactly `runs`
 * (plain rounding can overshoot or undershoot). Drivers who round to zero dots
 * fold into "others"; at most `maxNamed` drivers are named.
 */
export function replayStrip(
  distribution: Record<string, number>,
  runs: number = REPLAY_RUNS,
  maxNamed = 4,
): ReplayStrip {
  const entries = Object.entries(distribution)
    .filter(([, probability]) => Number.isFinite(probability) && probability > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const total = entries.reduce((sum, [, probability]) => sum + probability, 0);
  if (total <= 0) return { groups: [], allocation: {}, otherDots: runs, runs };

  // Normalize in case the distribution does not sum to exactly 1.
  const shares = entries.map(([driverId, probability]) => {
    const exact = (probability / total) * runs;
    return { driverId, floor: Math.floor(exact), remainder: exact - Math.floor(exact) };
  });
  let assigned = shares.reduce((sum, share) => sum + share.floor, 0);
  const byRemainder = [...shares].sort((a, b) => b.remainder - a.remainder);
  for (const share of byRemainder) {
    if (assigned >= runs) break;
    share.floor += 1;
    assigned += 1;
  }

  const allocation: Record<string, number> = Object.fromEntries(
    shares.map((share) => [share.driverId, share.floor]),
  );
  const named = shares.filter((share) => share.floor > 0).slice(0, maxNamed);
  const namedDots = named.reduce((sum, share) => sum + share.floor, 0);
  return {
    groups: named.map((share) => ({ driverId: share.driverId, dots: share.floor })),
    allocation,
    otherDots: runs - namedDots,
    runs,
  };
}

/** Spoken summary, e.g. "If this race ran 20 times: VER wins about 6, NOR about 4, all others 10." */
export function replaySummary(strip: ReplayStrip, label: (driverId: string) => string): string {
  const parts = strip.groups.map((group, index) =>
    index === 0 ? `${label(group.driverId)} wins about ${group.dots}` : `${label(group.driverId)} about ${group.dots}`,
  );
  if (strip.otherDots > 0) parts.push(`all others ${strip.otherDots}`);
  return `If this race ran ${strip.runs} times: ${parts.join(", ")}.`;
}

/**
 * Where the actual winner fell in the strip: "about 3 of 20 replays", or
 * "fewer than 1 of 20" for a long shot who rounds to zero dots. Null when the
 * winner is unknown or already shown as a named group.
 */
export function winnerNote(strip: ReplayStrip, winnerId: string | undefined): { count: number; text: string } | null {
  if (!winnerId || strip.groups.some((group) => group.driverId === winnerId)) return null;
  const count = strip.allocation[winnerId] ?? 0;
  return {
    count,
    text: count > 0 ? `about ${count} of ${strip.runs} replays` : `fewer than 1 of ${strip.runs} replays`,
  };
}
