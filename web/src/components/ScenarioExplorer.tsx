import { useState } from "react";
import type { InRaceScenario } from "../types";
import "./ScenarioExplorer.css";

/** Interact with signed, precomputed lap-scenario results. Never reruns inference. */
export function ScenarioExplorer({ scenario }: { scenario: InRaceScenario }) {
  const sorted = [...scenario.drivers].sort((a, b) => b.conditionalWinFrequency - a.conditionalWinFrequency);
  const [driverNumber, setDriverNumber] = useState<number | null>(sorted[0]?.driverNumber ?? null);
  const selected = sorted.find((entry) => entry.driverNumber === driverNumber) ?? sorted[0];

  if (!selected) {
    return <p className="empty-state">No driver outcomes are recorded in this checkpoint.</p>;
  }

  const winPercent = Math.max(0, Math.min(100, selected.conditionalWinFrequency * 100));
  const topFourPercent = Math.max(0, Math.min(100, selected.conditionalTopFourFrequency * 100));

  return (
    <section className="scenario-explorer" aria-label="Explore recorded checkpoint outcomes">
      <div className="scenario-explorer__header">
        <h2>Explore the race scenario</h2>
        <span>RECORDED RESEARCH</span>
      </div>
      <p className="scenario-explorer__help">Select a driver to inspect the model's stored continuation trials at lap {scenario.checkpointLap}. Changing drivers never triggers new inference.</p>
      <div className="scenario-explorer__drivers" aria-label="Choose a driver">
        {sorted.map((driver) => (
          <button key={driver.driverNumber} type="button"
            aria-pressed={selected.driverNumber === driver.driverNumber}
            className={"scenario-explorer__driver" + (selected.driverNumber === driver.driverNumber ? " is-selected" : "")}
            onClick={() => setDriverNumber(driver.driverNumber)}>
            #{driver.driverNumber} <small>P{driver.currentPosition}</small>
          </button>
        ))}
      </div>
      <div className="scenario-explorer__focus">
        <div className="scenario-explorer__focus-head">
          <strong>Driver #{selected.driverNumber}</strong>
          <span>Recorded position P{selected.currentPosition}</span>
        </div>
        <label htmlFor="scenario-win-frequency">
          Green-flag win frequency <strong>{winPercent.toFixed(1)}%</strong>
        </label>
        <progress id="scenario-win-frequency" max={100} value={winPercent} />
        <label htmlFor="scenario-top4-frequency">
          Green-flag top-four frequency <strong>{topFourPercent.toFixed(1)}%</strong>
        </label>
        <progress id="scenario-top4-frequency" max={100} value={topFourPercent} />
      </div>
      <p className="scenario-explorer__foot">Experimental conditional frequencies from {scenario.trials.toLocaleString()} recorded trials. Not calibrated probabilities, live car positions, or a new prediction.</p>
    </section>
  );
}
