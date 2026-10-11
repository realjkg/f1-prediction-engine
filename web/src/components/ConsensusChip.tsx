import { COIN_FLIP_SUFFIX, CONSENSUS_COPY } from "../lib/copy";
import type { ConsensusFlag } from "../types";

interface ConsensusChipProps {
  flag: ConsensusFlag;
  /** Show the coin-flip flavor on LOW_CONSENSUS rounds. */
  coinFlip?: boolean;
}

/**
 * Consensus flag chip — flagged, never suppressed. The text is plain language;
 * the engine's flag name stays on `data-flag` for tests and the Evidence Room.
 */
export function ConsensusChip({ flag, coinFlip = false }: ConsensusChipProps) {
  const isLow = flag === "LOW_CONSENSUS";
  const copy = CONSENSUS_COPY[flag];
  return (
    <span className={`consensus-chip${isLow ? " is-low" : ""}`} data-flag={flag} title={copy.hint}>
      {copy.label}
      {isLow && coinFlip ? ` · ${COIN_FLIP_SUFFIX}` : ""}
    </span>
  );
}
