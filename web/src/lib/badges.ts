/**
 * Badge rules (design doc §5) — pure evaluation over one finished round's
 * context. The App records earned badges into the pit-wall record; this module
 * never touches storage.
 */

import type { BadgeId } from "../types";
import { STREAK_FLAME_AT } from "./scoring";

export interface BadgeInfo {
  id: BadgeId;
  name: string;
  description: string;
}

/** The six ship badges, in catalog order. */
export const BADGES: Record<BadgeId, BadgeInfo> = {
  "first-exact-podium": {
    id: "first-exact-podium",
    name: "First Exact Podium",
    description: "Called a podium position-exact.",
  },
  "three-in-a-row": {
    id: "three-in-a-row",
    name: "Three In A Row",
    description: "Three rounds in a row with an exact podium hit.",
  },
  "beat-the-ensemble": {
    id: "beat-the-ensemble",
    name: "Beat The Ensemble",
    description: "Finished a season ahead of the ensemble. The rare one.",
  },
  "cold-read": {
    id: "cold-read",
    name: "Cold Read",
    description: "Called a winner the ensemble priced below 10%.",
  },
  "data-nerd": {
    id: "data-nerd",
    name: "Data Nerd",
    description: "Opened the Evidence Room five times.",
  },
  "perfect-round": {
    id: "perfect-round",
    name: "Perfect Round",
    description: "Called the winner and both other picks made the podium.",
  },
};

/** Evidence Room opens needed for Data Nerd (design doc §5). */
export const DATA_NERD_THRESHOLD = 5;

/** A winner pick at or under this ensemble probability counts as a cold read. */
export const COLD_READ_PROB_BELOW = 0.1;

/** Everything the badge evaluator needs about one finished round. */
export interface RoundBadgeInput {
  /** All three picks position-exact. */
  exactPodium: boolean;
  /** The P1 pick won. */
  winnerCalled: boolean;
  /** Ensemble win probability of the player's P1 pick; null when absent. */
  winnerProb: number | null;
  /** The P2 pick finished in the top three. */
  p2OnPodium: boolean;
  /** The P3 pick finished in the top three. */
  p3OnPodium: boolean;
  /** Streak count after this round's update. */
  streakAfterRound: number;
  /** Player's season points across all rounds played so far. */
  playerPoints: number;
  /** Ensemble's season points across the same rounds. */
  ensemblePoints: number;
  /** Evidence Room opens, including this round's. */
  evidenceViews: number;
}

/**
 * Badges earned by one finished round. Pure and idempotent — the caller
 * unions the result into the record's badge list.
 */
export function badgesForRound(input: RoundBadgeInput): BadgeId[] {
  const earned: BadgeId[] = [];
  if (input.exactPodium) {
    earned.push("first-exact-podium");
  }
  if (input.streakAfterRound >= STREAK_FLAME_AT) {
    earned.push("three-in-a-row");
  }
  if (input.playerPoints > input.ensemblePoints) {
    earned.push("beat-the-ensemble");
  }
  if (input.winnerCalled && input.winnerProb !== null && input.winnerProb < COLD_READ_PROB_BELOW) {
    earned.push("cold-read");
  }
  if (input.evidenceViews >= DATA_NERD_THRESHOLD) {
    earned.push("data-nerd");
  }
  if (input.winnerCalled && input.p2OnPodium && input.p3OnPodium) {
    earned.push("perfect-round");
  }
  return earned;
}

/** Badge display names for a record's earned ids, catalog order first. */
export function badgeInfos(ids: BadgeId[]): BadgeInfo[] {
  return Object.values(BADGES).filter((badge) => ids.includes(badge.id));
}
