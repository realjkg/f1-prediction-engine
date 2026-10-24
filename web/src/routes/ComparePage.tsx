import { useEffect, useMemo, useState } from "react";
import { EngineErrorPanel, Loading, ResourceView } from "../components/EngineError";
import { formatPercent } from "../lib/baseline";
import { useEngineClient, useResource } from "../lib/engine";
import type { CatalogRace, PredictionEnvelope } from "../types";
import { ModeBadge, RacePicker, defaultSelection, findRace, type RaceSelection } from "./PredictionsPage";

interface ComparePageProps {
  selection: RaceSelection | null;
  onSelect: (selection: RaceSelection) => void;
}

/**
 * Driver and team comparison for one race, from the same served prediction:
 * the model inputs side by side and each team's combined win chance. Nothing
 * here is computed beyond adding a team's drivers' win chances together.
 */
export function ComparePage({ selection, onSelect }: ComparePageProps) {
  const client = useEngineClient();
  const catalog = useResource(() => client.getPredictionCatalog(), []);
  useEffect(() => {
    if (catalog.status === "ready" && !findRace(catalog.data, selection)) {
      const fallback = defaultSelection(catalog.data);
      if (fallback) onSelect(fallback);
    }
  }, [catalog, selection, onSelect]);

  return (
    <section className="compare" aria-labelledby="compare-title">
      <h1 id="compare-title">Compare drivers and teams</h1>
      <p className="screen-intro">
        Two drivers' model inputs side by side, and each team's combined chance to win, for one race.
      </p>
      <ResourceView
        resource={catalog}
        context="Race catalog"
        ready={(view) => {
          const race = findRace(view, selection);
          return (
            <>
              <div className="prediction-controls">
                <RacePicker catalog={view} selection={selection} onSelect={onSelect} />
              </div>
              {race && race.predictionMode !== "unavailable" ? (
                <CompareBody race={race} />
              ) : race ? (
                <div className="unavailable-panel" role="status">
                  <ModeBadge mode="unavailable" />
                  <p>{race.checkpoints[0]?.reason ?? "No supported prediction for this race."}</p>
                </div>
              ) : null}
            </>
          );
        }}
      />
    </section>
  );
}

function CompareBody({ race }: { race: CatalogRace }) {
  const client = useEngineClient();
  const prediction = useResource(
    () => client.getRacePrediction(race.raceId, race.season, "pre-weekend"),
    [race.raceId, race.season],
  );
  if (prediction.status === "loading") return <Loading label="Prediction" />;
  if (prediction.status === "error") {
    return <EngineErrorPanel error={prediction.error} onRetry={prediction.retry} context="Prediction" />;
  }
  return <Comparison key={`${race.season}-${race.raceId}`} envelope={prediction.data} />;
}

export function Comparison({ envelope }: { envelope: PredictionEnvelope }) {
  const drivers = envelope.drivers;
  const [left, setLeft] = useState(drivers[0]?.driverId ?? "");
  const [right, setRight] = useState(drivers[1]?.driverId ?? "");
  const a = drivers.find((driver) => driver.driverId === left);
  const b = drivers.find((driver) => driver.driverId === right);
  const teams = useMemo(() => {
    const totals = new Map<string, { name: string; chance: number; drivers: string[] }>();
    for (const driver of drivers) {
      const entry = totals.get(driver.constructorId) ?? { name: driver.constructorName, chance: 0, drivers: [] };
      entry.chance += driver.winProbability;
      entry.drivers.push(driver.driverCode);
      totals.set(driver.constructorId, entry);
    }
    return [...totals.values()].sort((x, y) => y.chance - x.chance);
  }, [drivers]);

  const picker = (label: string, value: string, onChange: (value: string) => void) => (
    <label className="race-picker">
      <span className="race-picker-label">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {drivers.map((driver) => (
          <option key={driver.driverId} value={driver.driverId}>
            {driver.driverName} ({driver.constructorName})
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="compare-body">
      <p className="race-context">
        <ModeBadge mode={envelope.predictionMode} /> {envelope.season} {envelope.raceName} · before the race weekend
      </p>
      <div className="prediction-controls">
        {picker("First driver", left, setLeft)}
        {picker("Second driver", right, setRight)}
      </div>
      {a && b && (
        <table className="win-table compare-table">
          <caption>Model inputs as of the checkpoint (data through the previous race)</caption>
          <thead>
            <tr>
              <th scope="col">Input</th>
              <th scope="col">{a.driverName}</th>
              <th scope="col">{b.driverName}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Chance to win (ensemble)</th>
              <td className="num">{formatPercent(a.winProbability)}</td>
              <td className="num">{formatPercent(b.winProbability)}</td>
            </tr>
            {Object.entries(envelope.featureLabels).map(([key, label]) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                <td className="num">{formatFeature(a.features[key])}</td>
                <td className="num">{formatFeature(b.features[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="data-note">"No data" means the input was missing for that driver; the models leave it missing rather than guessing.</p>

      <h2>Teams</h2>
      <table className="win-table">
        <caption>Each team's chance that one of its drivers wins: its drivers' chances added together</caption>
        <thead>
          <tr><th scope="col">Team</th><th scope="col">Drivers</th><th scope="col">Chance to win</th></tr>
        </thead>
        <tbody>
          {teams.map((team) => (
            <tr key={team.name}>
              <th scope="row">{team.name}</th>
              <td>{team.drivers.join(", ")}</td>
              <td>
                <span className="win-cell"><span className="win-bar" aria-hidden="true"><span style={{ width: `${Math.max(team.chance * 100, 0.5)}%` }} /></span>
                <span className="num">{formatPercent(team.chance)}</span></span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatFeature(value: number | null | undefined): string {
  if (value === null || value === undefined) return "No data";
  return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}
