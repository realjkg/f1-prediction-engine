import { useEffect, useState } from "react";
import { EngineErrorPanel, Loading, ResourceView } from "../components/EngineError";
import { formatPercent } from "../lib/baseline";
import { competitorColor } from "../lib/colors";
import { useEngineClient, useResource } from "../lib/engine";
import type {
  CatalogRace,
  Checkpoint,
  DriverForecast,
  PredictionCatalogView,
  PredictionEnvelope,
  RaceResultView,
} from "../types";

/** The race the visitor is looking at; held in memory by the app shell. */
export interface RaceSelection {
  raceId: string;
  season: number;
}

const MODE_LABELS: Record<string, string> = {
  "historical-backtest": "HISTORICAL",
  "pre-race": "PRE-RACE",
  unavailable: "UNAVAILABLE",
  scenario: "SCENARIO",
  synthetic: "SYNTHETIC",
  live: "LIVE",
};

const MODE_HINTS: Record<string, string> = {
  "historical-backtest":
    "A finished race replayed: the prediction uses only data from before the weekend.",
  "pre-race": "A prediction for a race that has not happened yet.",
  unavailable: "No supported prediction for this race.",
};

const CHECKPOINT_LABELS: Record<Checkpoint, string> = {
  "pre-weekend": "Before the race weekend",
  "post-qualifying": "After qualifying",
};

const VISIBLE_ROWS = 10;

export function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className={`mode-badge mode-${mode}`} title={MODE_HINTS[mode]}>
      <span className="visually-hidden">Prediction mode: </span>
      {MODE_LABELS[mode] ?? mode.toUpperCase()}
    </span>
  );
}

export function raceLabel(race: CatalogRace): string {
  return `${race.season} · Round ${race.round} · ${race.name}`;
}

/** Latest race with a supported prediction, else the latest race. */
export function defaultSelection(catalog: PredictionCatalogView): RaceSelection | null {
  const pick = catalog.races.find((race) => race.predictionMode !== "unavailable") ?? catalog.races[0];
  return pick ? { raceId: pick.raceId, season: pick.season } : null;
}

export function findRace(catalog: PredictionCatalogView, selection: RaceSelection | null): CatalogRace | null {
  if (!selection) return null;
  return catalog.races.find((race) => race.raceId === selection.raceId && race.season === selection.season) ?? null;
}

interface RacePickerProps {
  catalog: PredictionCatalogView;
  selection: RaceSelection | null;
  onSelect: (selection: RaceSelection) => void;
}

export function RacePicker({ catalog, selection, onSelect }: RacePickerProps) {
  const seasons = [...new Set(catalog.races.map((race) => race.season))];
  const value = selection ? `${selection.season}|${selection.raceId}` : "";
  return (
    <label className="race-picker">
      <span className="race-picker-label">Race</span>
      <select
        value={value}
        onChange={(event) => {
          const [season, raceId] = event.target.value.split("|");
          onSelect({ raceId, season: Number(season) });
        }}
      >
        {seasons.map((season) => (
          <optgroup key={season} label={String(season)}>
            {catalog.races
              .filter((race) => race.season === season)
              .map((race) => (
                <option key={`${race.season}|${race.raceId}`} value={`${race.season}|${race.raceId}`}>
                  {`R${race.round} ${race.name}${race.predictionMode === "unavailable" ? " (no prediction)" : ""}`}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

interface PredictionsPageProps {
  selection: RaceSelection | null;
  onSelect: (selection: RaceSelection) => void;
  onCompare: () => void;
}

/**
 * Race Predictions — the primary screen. Shows only what the engine supports
 * for the chosen race and checkpoint, with its mode, cutoff, freshness, model
 * evidence, missing inputs and validation; never a substitute prediction.
 */
export function PredictionsPage({ selection, onSelect, onCompare }: PredictionsPageProps) {
  const client = useEngineClient();
  const catalog = useResource(() => client.getPredictionCatalog(), []);
  const [checkpoint, setCheckpoint] = useState<Checkpoint>("pre-weekend");

  useEffect(() => {
    if (catalog.status === "ready" && !findRace(catalog.data, selection)) {
      const fallback = defaultSelection(catalog.data);
      if (fallback) onSelect(fallback);
    }
  }, [catalog, selection, onSelect]);

  return (
    <section className="predictions" aria-labelledby="predictions-title">
      <h1 id="predictions-title">Race predictions</h1>
      <p className="screen-intro">
        Who is likely to win, using only data available before the race. Every number says
        which race, which checkpoint and which data it comes from.
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
                {race && (
                  <fieldset className="checkpoint-picker">
                    <legend>Checkpoint</legend>
                    {race.checkpoints.map((option) => (
                      <label key={option.checkpoint} className={option.supported ? "" : "is-unsupported"}>
                        <input
                          type="radio"
                          name="checkpoint"
                          value={option.checkpoint}
                          checked={checkpoint === option.checkpoint}
                          onChange={() => setCheckpoint(option.checkpoint)}
                        />
                        {CHECKPOINT_LABELS[option.checkpoint]}
                        {!option.supported && <span className="unsupported-tag"> (not supported)</span>}
                      </label>
                    ))}
                  </fieldset>
                )}
              </div>
              {view.upcomingRaces === 0 && <p className="data-note">{view.upcomingNote}</p>}
              {race && <RaceSection race={race} checkpoint={checkpoint} catalog={view} onCompare={onCompare} />}
            </>
          );
        }}
      />
    </section>
  );
}

function RaceSection({ race, checkpoint, catalog, onCompare }: {
  race: CatalogRace;
  checkpoint: Checkpoint;
  catalog: PredictionCatalogView;
  onCompare: () => void;
}) {
  const support = race.checkpoints.find((option) => option.checkpoint === checkpoint);
  const supported = race.predictionMode !== "unavailable" && support?.supported === true;
  return (
    <article className="race-prediction" aria-label={`Prediction for ${race.season} ${race.name}`}>
      <header className="race-prediction-head">
        <div>
          <h2>{race.season} {race.name}</h2>
          <p className="race-context">
            Round {race.round} · {race.circuitName}, {race.country} · Race day {race.raceDate}
          </p>
        </div>
        <ModeBadge mode={supported ? race.predictionMode : "unavailable"} />
      </header>
      {supported ? (
        <PredictionBody race={race} checkpoint={checkpoint} onCompare={onCompare} />
      ) : (
        <UnavailablePanel reason={support?.reason ?? null} catalog={catalog} />
      )}
    </article>
  );
}

function UnavailablePanel({ reason, catalog }: { reason: string | null; catalog: PredictionCatalogView }) {
  return (
    <div className="unavailable-panel" role="status">
      <h3>No prediction for this selection</h3>
      <p>{reason ?? "This race has no supported prediction."}</p>
      <dl className="ledger-meta">
        <div><dt>Last verified data update</dt><dd>{catalog.dataThroughDate} (latest race in the data)</dd></div>
        <div><dt>Dataset</dt><dd className="num">{catalog.datasetId}</dd></div>
      </dl>
      <p className="data-note">
        Still usable: the {catalog.supportedTotal} races with a supported prediction, Model Performance
        and Data &amp; Evidence.
      </p>
    </div>
  );
}

function PredictionBody({ race, checkpoint, onCompare }: {
  race: CatalogRace;
  checkpoint: Checkpoint;
  onCompare: () => void;
}) {
  const client = useEngineClient();
  const prediction = useResource(
    () => client.getRacePrediction(race.raceId, race.season, checkpoint),
    [race.raceId, race.season, checkpoint],
  );
  if (prediction.status === "loading") return <Loading label="Prediction" />;
  if (prediction.status === "error") {
    return <EngineErrorPanel error={prediction.error} onRetry={prediction.retry} context="Prediction" />;
  }
  return <PredictionDetails envelope={prediction.data} onCompare={onCompare} />;
}

export function PredictionDetails({ envelope, onCompare }: { envelope: PredictionEnvelope; onCompare: () => void }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? envelope.drivers : envelope.drivers.slice(0, VISIBLE_ROWS);
  const cutoff = envelope.featureCutoff;
  const failed = envelope.validation.filter((check) => !check.passed);
  return (
    <div className="prediction-grid">
      <section className="prediction-main" aria-labelledby="win-table-title">
        <p className="freshness-note">{envelope.freshnessNote}</p>
        <h3 id="win-table-title">Chance to win</h3>
        <table className="win-table">
          <caption className="visually-hidden">
            Win probability per driver from the ensemble of {envelope.models.length} models, with each model's own number.
          </caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Driver</th>
              <th scope="col" className="col-team">Team</th>
              <th scope="col">Win chance</th>
              {envelope.models.map((model) => (
                <th scope="col" key={model} className="col-model">
                  <span className="model-key" style={{ borderColor: competitorColor(model) }}>{model}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((driver) => (
              <tr key={driver.driverId}>
                <td className="num">{driver.rank}</td>
                <th scope="row">
                  <span className="driver-code">{driver.driverCode}</span> {driver.driverName}
                </th>
                <td className="col-team">{driver.constructorName}</td>
                <td>
                  <span className="win-cell"><span className="win-bar" aria-hidden="true">
                    <span style={{ width: `${Math.max(driver.winProbability * 100, 0.5)}%` }} />
                  </span>
                  <span className="num">{formatPercent(driver.winProbability)}</span></span>
                </td>
                {envelope.models.map((model) => (
                  <td key={model} className="num col-model">
                    {formatPercent(driver.perModelWinProbability[model] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {envelope.drivers.length > VISIBLE_ROWS && (
          <button type="button" className="text-button" onClick={() => setShowAll((value) => !value)}>
            {showAll ? `Show top ${VISIBLE_ROWS}` : `Show all ${envelope.drivers.length} drivers`}
          </button>
        )}
        <p className="baseline-note">
          Baseline: {envelope.baseline.detail} That is {formatPercent(envelope.baseline.winProbability)} each.
          {envelope.consensusFlag === "LOW_CONSENSUS" ? " The three models disagree on the podium for this race." : ""}
        </p>
        <Explanations drivers={envelope.drivers.slice(0, 3)} onCompare={onCompare} />
        {envelope.outcomeAvailable && <OutcomeReveal envelope={envelope} />}
      </section>

      <aside className="prediction-side" aria-label="Prediction details">
        <section aria-labelledby="facts-title">
          <h3 id="facts-title">What this is based on</h3>
          <dl className="ledger-meta">
            <div><dt>Checkpoint</dt><dd>{CHECKPOINT_LABELS[envelope.checkpoint]}</dd></div>
            <div>
              <dt>Data used up to</dt>
              <dd>
                {cutoff.throughRaceName
                  ? `${cutoff.throughSeason} ${cutoff.throughRaceName} (${cutoff.throughRaceDate})`
                  : "No earlier races in the data"}
              </dd>
            </div>
            <div><dt>Not used</dt><dd>{cutoff.excludes.join("; ")}</dd></div>
            <div><dt>Prediction made</dt><dd>{envelope.predictionGeneratedAt ?? "Replayed later; original time not recorded"}</dd></div>
            <div><dt>Source data retrieved</dt><dd className="num">{envelope.sourceUpdatedAt.slice(0, 10)}</dd></div>
            <div><dt>Models</dt><dd className="num">{envelope.modelRevision}</dd></div>
            <div><dt>Dataset</dt><dd className="num">{envelope.datasetId} · {envelope.datasetDigest.slice(0, 12)}…</dd></div>
            <div><dt>Evidence record</dt><dd className="num">{envelope.evidencePredictionId}</dd></div>
          </dl>
        </section>

        <section aria-labelledby="outputs-title">
          <h3 id="outputs-title">Outputs</h3>
          <ul className="support-list">
            {envelope.outputs.map((output) => (
              <li key={output.output} className={output.supported ? "is-supported" : "is-unsupported"}>
                <strong>{output.supported ? "✓ Shown" : "✕ Not shown"}: {OUTPUT_LABELS[output.output]}</strong>
                <span>{output.reason}</span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="missing-title">
          <h3 id="missing-title">Inputs this prediction does not have</h3>
          <ul className="support-list">
            {envelope.missingInputs.map((input) => (
              <li key={input.input} className="is-unsupported">
                <strong>{input.input}</strong>
                <span>{input.detail} Needs: {input.sourceNeeded}.</span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="checks-title">
          <h3 id="checks-title">Checks on these numbers</h3>
          <p className="data-note">
            {failed.length === 0
              ? `All ${envelope.validation.length} checks passed.`
              : `${envelope.validation.length - failed.length} of ${envelope.validation.length} checks passed.`}
          </p>
          <ul className="check-list">
            {envelope.validation.map((check) => (
              <li key={check.check} className={check.passed ? "is-pass" : "is-fail"}>
                <span aria-hidden="true">{check.passed ? "✓ " : "✕ "}</span>
                <span className="visually-hidden">{check.passed ? "Passed: " : "Failed: "}</span>
                {check.check} <span className="check-detail">({check.detail})</span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="limits-title">
          <h3 id="limits-title">Limitations</h3>
          <ul className="limit-list">
            {envelope.limitations.map((limit) => <li key={limit}>{limit}</li>)}
          </ul>
          <p className="data-note">
            Sources: {envelope.provenance.map((source) => `${source.provider} (${source.license})`).join(", ")}.
            Advisory only; not betting advice.
          </p>
        </section>
      </aside>
    </div>
  );
}

const OUTPUT_LABELS: Record<string, string> = {
  winner: "Win probability",
  podium: "Podium probability",
  points: "Points finish",
  finishPosition: "Finishing position",
  dnfRisk: "Retirement risk",
  intervals: "Uncertainty ranges",
};

function Explanations({ drivers, onCompare }: { drivers: DriverForecast[]; onCompare: () => void }) {
  return (
    <section className="explanations" aria-labelledby="why-title">
      <h3 id="why-title">How the favorites' inputs compare</h3>
      <p className="data-note">
        These notes compare each driver's model inputs with the rest of the field. They describe the
        inputs, not the causes of a result.
      </p>
      <ul>
        {drivers.map((driver) => (
          <li key={driver.driverId}>
            <strong>{driver.driverName}</strong> ({formatPercent(driver.winProbability)})
            {driver.reasons.length > 0 ? (
              <ul>{driver.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            ) : (
              <p className="data-note">No input ranks in the field's top three.</p>
            )}
          </li>
        ))}
      </ul>
      <button type="button" className="text-button" onClick={onCompare}>Compare drivers and teams</button>
    </section>
  );
}

function OutcomeReveal({ envelope }: { envelope: PredictionEnvelope }) {
  const client = useEngineClient();
  const [result, setResult] = useState<
    { status: "idle" } | { status: "loading" } | { status: "ready"; data: RaceResultView } | { status: "error"; message: string }
  >({ status: "idle" });
  const reveal = () => {
    setResult({ status: "loading" });
    client.getRaceResult(envelope.raceId, envelope.season).then(
      (data) => setResult({ status: "ready", data }),
      (error: unknown) => setResult({ status: "error", message: error instanceof Error ? error.message : String(error) }),
    );
  };
  if (result.status === "idle") {
    return (
      <button type="button" className="text-button reveal-button" onClick={reveal}>
        This race is finished. Show how the prediction did
      </button>
    );
  }
  if (result.status === "loading") return <p role="status">Loading the result…</p>;
  if (result.status === "error") return <p role="alert">Could not load the result: {result.message}</p>;
  const winner = envelope.drivers.find((driver) => driver.driverId === result.data.winner);
  return (
    <p className="outcome-note" role="status">
      Actual winner: <strong>{winner?.driverName ?? result.data.winner}</strong>
      {winner ? `, ranked ${winner.rank} with ${formatPercent(winner.winProbability)} before the weekend.` : "."}
    </p>
  );
}
