import { useEffect, useState, type FormEvent } from "react";
import { EngineErrorPanel, Loading } from "../components/EngineError";
import "./live-lab-status.css";
import { useEngineClient, useResource } from "../lib/engine";
import type { InRaceAccuracyReport, InRaceRunArtifact, UpdatedScenario } from "../types";

const formatNumber = (value: number) => value.toFixed(1);

/**
 * In-race Lab — reads a VERIFIED local artifact. Never synthesizes a new
 * prediction from a user's lap input, and never labels research as live.
 */
export function LiveLabPage() {
  const client = useEngineClient();
  const [raceInput, setRaceInput] = useState("singapore");
  const [seasonInput, setSeasonInput] = useState("2026");
  const [lapInput, setLapInput] = useState("");
  const [query, setQuery] = useState({ raceId: "singapore", season: 2026, lap: undefined as number | undefined });
  const [tick, setTick] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(false);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => setTick((previous) => previous + 1), 15000);
    return () => clearInterval(id);
  }, [autoRefresh]);

  const result = useResource(
    () => client.getLapScenario(query.raceId, query.season, query.lap),
    [query.raceId, query.season, query.lap, tick],
  );

  const fusion = useResource(
    () => client.getLapFusion(query.raceId, query.season, query.lap),
    [query.raceId, query.season, query.lap, tick],
  );

  const accuracy = useResource(() => client.getInraceAccuracy(), [tick]);

  const run = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const raceId = raceInput.trim().toLowerCase();
    const season = Number(seasonInput);
    const lap = lapInput.trim() ? Number(lapInput) : undefined;
    if (!/^[a-z0-9_-]{1,100}$/.test(raceId) ||
        !Number.isInteger(season) || season < 1950 || season > 2100 ||
        (lap !== undefined && (!Number.isInteger(lap) || lap < 1 || lap > 100))) {
      return;
    }
    setQuery({ raceId, season, lap });
    setTick((previous) => previous + 1);
  };

  return (
    <section className="live-lab" aria-label="In-race analysis">
      <h1>In-race Lab</h1>
      <p className="screen-intro">
        Shows verified lap checkpoints and experimental finish scenarios: recorded
        replays, or the latest lap from the live ingest when it is running. Leave Lap
        blank to follow the latest checkpoint. The source label on each checkpoint says
        which kind it is, and a stored artifact alone is not proof a feed is connected.
      </p>
      <div className="advisory-banner is-warning">
        Research mode. Scenario frequencies are not calibrated winner probabilities.
        No automatic model promotion or live betting recommendations.
      </div>

      <section className="feed-health" aria-label="Live feed and inference status">
        <div className="feed-health__header">
          <h2>Timing feed &amp; inference</h2>
          <span className="feed-health__tag">LIVE NOT VERIFIED</span>
        </div>
        <dl className="feed-health__grid">
          <div className="feed-health__cell">
            <dt>Checkpoint source</dt>
            <dd>{result.status === "ready"
              ? "Stored: " + result.data.sourceType
              : result.status === "loading"
                ? "Checking stored evidence"
                : result.error.code === "LIVE_SCENARIO_UNAVAILABLE"
                  ? "Not configured"
                  : "No verified checkpoint"}</dd>
          </div>
          <div className="feed-health__cell">
            <dt>Inference</dt>
            <dd>Read-only artifacts; no on-demand prediction</dd>
          </div>
          <div className="feed-health__cell">
            <dt>Updates</dt>
            <dd>Manual or 15-second polling; not a live stream</dd>
          </div>
        </dl>
        <p className="feed-health__detail">
          For a live race, a licensed timing stream must first reach a private, persistent
          collector. A separate inference worker must then generate, qualify, and publish
          timestamped evidence. This Vercel demo cannot perform that work by refreshing the page.
        </p>
      </section>
      <form className="live-lab-form" onSubmit={run}>
        <label htmlFor="live-race">Race slug
          <input id="live-race" value={raceInput} required onChange={(e) => setRaceInput(e.target.value)} />
        </label>
        <label htmlFor="live-season">Season
          <input id="live-season" type="number" min="1950" max="2100" value={seasonInput}
            required onChange={(e) => setSeasonInput(e.target.value)} />
        </label>
        <label htmlFor="live-lap">Lap
          <input id="live-lap" type="number" min="1" max="100" value={lapInput}
            placeholder="Latest" onChange={(e) => setLapInput(e.target.value)} />
        </label>
        <button className="primary-button" type="submit">Load verified checkpoint</button>
      </form>
      <label className="live-auto">
        <input type="checkbox" checked={autoRefresh}
          onChange={(e) => setAutoRefresh(e.target.checked)} />
        Refresh server artifacts every 15 seconds
      </label>

      {result.status === "loading" ? <Loading label="Verified in-race artifact" /> : null}
      {result.status === "error" ? (
        <div role="status">
          <EngineErrorPanel context="Verified in-race artifact" error={result.error} onRetry={result.retry} />
          <p className="screen-intro">
            If this race has no licensed timing source or recorded checkpoint, there
            is no simulation to show. The app never invents positions or gaps.
          </p>
        </div>
      ) : null}
      {result.status === "ready" ? <ScenarioDetails artifact={result.data} /> : null}
      {result.status === "ready" && result.data.scenario !== null && (
        <section aria-label="Pre-race and current-lap comparison">
          {fusion.status === "ready" ? (
            fusion.data.checkpointSha256 === result.data.checkpointSha256 ? (
              <PriorComparison fusion={fusion.data} />
            ) : (
              <p className="advisory-banner is-warning">
                Frozen model source does not match this lap. Comparison withheld.
              </p>
            )
          ) : fusion.status === "loading" ? (
            <p className="screen-intro">Checking for a matching frozen pre-race model…</p>
          ) : fusion.error.code === "PRIOR_FUSION_NOT_FOUND" ? (
            <p className="empty-state">
              No matching, frozen pre-race model artifact was recorded for this checkpoint.
              Showing the lap-only scenario, without implying a combined prediction.
            </p>
          ) : (
            <EngineErrorPanel error={fusion.error} onRetry={fusion.retry}
              context="Frozen pre-race model comparison" />
          )}
        </section>
      )}
      <section className="live-fusion" aria-label="Chronological model accuracy">
        <h2>Model accuracy qualification</h2>
        {accuracy.status === "loading" && <Loading label="research accuracy evidence" />}
        {accuracy.status === "error" && (
          accuracy.error.code === "ACCURACY_REPORT_UNAVAILABLE" ? (
            <p className="empty-state" role="status">
              No verified forward-only accuracy report is configured. The app will
              not claim that its current-lap predictions outperform the baseline.
            </p>
          ) : (
            <EngineErrorPanel
              error={accuracy.error}
              onRetry={accuracy.retry}
              context="Chronological winner accuracy"
            />
          )
        )}
        {accuracy.status === "ready" && <AccuracyEvidence report={accuracy.data} />}
      </section>
    </section>
  );
}

function AccuracyEvidence({ report }: { report: InRaceAccuracyReport }) {
  if (!report.researchOnly || report.modelPromotionAllowed) {
    return <p className="advisory-banner is-warning">
      Invalid qualification status. Accuracy evidence cannot be displayed.
    </p>;
  }
  const labels: Array<[string, string]> = [
    ["pre-race", "Frozen pre-race model"],
    ["running-order", "Leader at checkpoint"],
    ["green-continuation", "Green-flag pace"],
    ["walkforward-fusion", "Forward-selected combination"],
  ];
  return (
    <div aria-label="Research accuracy comparison">
      <p className="screen-intro">
        {report.scoredRaces} later completed races scored; {report.unscoredRaces}
        {" "}races lacked enough earlier training results.
        One checkpoint per race. No weights selected using the target race outcome.
      </p>
      <div className="advisory-banner is-warning">
        Research diagnostic only. Winner hit rate and proper scores do not
        establish prospective accuracy, calibration, or production readiness.
      </div>
      <table className="standings-table">
        <thead><tr><th scope="col">Method</th><th scope="col">Winner hit</th>
          <th scope="col">Brier ↓</th><th scope="col">Log loss ↓</th></tr></thead>
        <tbody>
          {labels.map(([key, name]) => {
            const value = report.pairedSummary[key];
            return value ? (
              <tr key={key}>
                <th scope="row">{name}</th>
                <td>{(value.winnerHitRate * 100).toFixed(1)}%</td>
                <td>{value.meanMulticlassBrier.toFixed(3)}</td>
                <td>{value.meanWinnerLogLoss.toFixed(3)}</td>
              </tr>
            ) : null;
          })}
        </tbody>
      </table>
      <p className="screen-intro">
        Evaluation artifact <code>{report.reportSha256.slice(0, 20)}…</code>.
        No model has been automatically promoted.
      </p>
    </div>
  );
}

function ScenarioDetails({ artifact }: { artifact: InRaceRunArtifact }) {
  const scenario = artifact.scenario;
  return (
    <div className="live-artifact" aria-label="Simulation artifact">
      <div className="live-summary">
        <span className="live-value">Lap {artifact.lap}{scenario ? ` / ${scenario.totalLaps}` : ""}</span>
        <span className="live-pill">{artifact.sourceType}</span>
      </div>
      <p className="screen-intro">
        Source recorded {new Date(artifact.generatedAt).toLocaleString()}.
        Snapshot digest <code>{artifact.checkpointSha256.slice(0, 16)}…</code>.
      </p>
      {artifact.sourceType === "synthetic-fixture" && (
        <p className="advisory-banner is-warning">
          Synthetic test fixture. These positions and results are NOT from a real race.
        </p>
      )}
      {!scenario ? (
        <div className="empty-state" role="status">
          Scenario refused: {artifact.refusalReason ?? "Insufficient verified lap-state data."}
          The recorded lap trace is still available through the API.
        </div>
      ) : (
        <>
          <p className="screen-intro">
            {scenario.remainingLaps} laps remaining at this checkpoint.
            {scenario.trials.toLocaleString()} deterministic conditional trials.
            Frozen as of {new Date(scenario.observedAt).toLocaleString()}.
          </p>
          <h2>Observed vs. conditional scenario</h2>
          <table className="standings-table">
            <thead><tr><th scope="col">Driver #</th><th scope="col">Now</th>
              <th scope="col">Green-flag win frequency</th><th scope="col">Top 4</th></tr></thead>
            <tbody>
              {[...scenario.drivers]
                .sort((a, b) => b.conditionalWinFrequency - a.conditionalWinFrequency)
                .map((driver) => (
                  <tr key={driver.driverNumber}>
                    <th scope="row">#{driver.driverNumber}</th>
                    <td>P{driver.currentPosition}</td>
                    <td>{formatNumber(driver.conditionalWinFrequency * 100)}%</td>
                    <td>{formatNumber(driver.conditionalTopFourFrequency * 100)}%</td>
                  </tr>
                ))}
            </tbody>
          </table>
          <h2>Model assumptions</h2>
          <ul className="live-assumptions">
            {scenario.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
          </ul>
        </>
      )}
      <p className="screen-intro">
        Artifact SHA-256: <code>{artifact.artifactSha256.slice(0, 24)}…</code>.
        This is read-only evidence, not a live production prediction.
      </p>
    </div>
  );
}


function PriorComparison({ fusion }: { fusion: UpdatedScenario }) {
  return (
    <section aria-label="Research model comparison" className="live-fusion">
      <h2>Pre-race model + latest recorded lap</h2>
      <p className="advisory-banner is-warning">
        Experimental blend, not a qualified winner forecast. Coefficients have not
        passed chronological out-of-sample calibration. No promotion.
      </p>
      <p className="screen-intro">
        Model revision: <code>{fusion.modelRevision}</code>.
        Prior frozen: {new Date(fusion.priorFrozenAt).toLocaleString()}.
        Prior weight {(fusion.priorWeight * 100).toFixed(0)}%;
        lap scenario weight {(fusion.greenScenarioWeight * 100).toFixed(0)}%.
      </p>
      <table className="standings-table">
        <thead>
          <tr><th scope="col">Driver #</th><th scope="col">Pre-race</th>
            <th scope="col">Current lap</th><th scope="col">Combined research</th></tr>
        </thead>
        <tbody>
          {[...fusion.candidates].sort(
            (a,b) => b.blendedResearchWeight - a.blendedResearchWeight
          ).map((c) => (
            <tr key={c.driverNumber}>
              <th scope="row">#{c.driverNumber}</th>
              <td>{(100 * c.preRaceProbability).toFixed(1)}%</td>
              <td>{(100 * c.greenContinuationFrequency).toFixed(1)}%</td>
              <td>{(100 * c.blendedResearchWeight).toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="screen-intro">
        Pre-race dataset <code>{fusion.sourceDatasetSha256.slice(0,16)}…</code>.
        Fusion SHA-256 <code>{fusion.outputSha256.slice(0,16)}…</code>.
      </p>
    </section>
  );
}
