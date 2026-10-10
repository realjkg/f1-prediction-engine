import type { ConsensusFlag } from "../types";

interface ConsensusChipProps {
  flag: ConsensusFlag;
  /** Show the coin-flip flavor on LOW_CONSENSUS rounds. */
  coinFlip?: boolean;
}

/** Consensus flag chip — flagged, never suppressed. */
export function ConsensusChip({ flag, coinFlip = false }: ConsensusChipProps) {
  const isLow = flag === "LOW_CONSENSUS";
  return (
    <span className={`consensus-chip${isLow ? " is-low" : ""}`} data-flag={flag}>
      {flag}
      {isLow && coinFlip ? " · COIN FLIP — POINTS DOUBLE" : ""}
    </span>
  );
}
