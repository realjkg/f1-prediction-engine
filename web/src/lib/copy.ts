/**
 * Plain-language labels for engine vocabulary. The engine's flag names stay in
 * the data attributes and the Evidence Room; everywhere else the UI says what
 * the flag means.
 */

import type { ConsensusFlag } from "../types";

export interface ConsensusCopy {
  label: string;
  /** One short sentence for tooltips and screen readers. */
  hint: string;
}

export const CONSENSUS_COPY: Record<ConsensusFlag, ConsensusCopy> = {
  OK: {
    label: "Models agree",
    hint: "The models picked a similar podium, so this forecast is on firmer ground.",
  },
  LOW_CONSENSUS: {
    label: "Models disagree",
    hint: "The models split on this race. Treat it as a coin flip; points double if you call it.",
  },
};

/** Suffix added to the low-consensus chip when the round is scored for the game. */
export const COIN_FLIP_SUFFIX = "Coin flip, points double";
