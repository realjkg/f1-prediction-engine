import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ResourceView } from "../components/EngineError";
import { useEngineClient, useResource } from "../lib/engine";
import { COMPETITOR_NAMES, playedRounds, seasonStandings } from "../lib/standings";
import type { BacktestRecord, PitWallRecord } from "../types";

interface ModelsPageProps {
  record: PitWallRecord;
}

/** Measured accuracy — the ledger's backtest record, rendered as the Gauntlet's proof. */
function BacktestPanel({ backtest }: { backtest: BacktestRecord }) {
  const competitorOrder = ["m1-gbm", "m2-logit", "m3-form", "ensemble"];
  const rows = competitorOrder
    .filter((id) => backtest.metrics[id] != null)
    .map((id) => ({ id, ...backtest.metrics[id] }));
  return (
    <section aria-label="Backtest accuracy" className="backtest-panel">
      <h2>
        Backtest — {backtest.season}, rounds {backtest.firstRound}–{backtest.lastRound} ({backtest.roundsScored}{" "}
        scored)
      </h2>
      <table className="standings-table">
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Winner hit</th>
            <th scope="col">Podium@3</th>
            <th scope="col">Mean Brier</th>
            <th scope="col">Rounds</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <th scope="row">{COMPETITOR_NAMES[row.id as keyof typeof COMPETITOR_NAMES] ?? row.id}</th>
              <td>{Math.round(row.winnerHitRate * 100)}%</td>
              <td>{Math.round(row.podium3HitRate * 100)}%</td>
              <td>{row.meanBrier.toFixed(3)}</td>
              <td>{row.rounds}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="metric-definitions">
        <summary>What these mean</summary>
        <dl>
          {Object.entries(backtest.metricDefinitions).map(([metric, definition]) => (
            <div key={metric}>
              <dt>{metric}</dt>
              <dd>{definition}</dd>
            </div>
          ))}
        </dl>
      </details>
      <p className="ledger-basis">{backtest.evidenceBasis}</p>
      {backtest.skippedRounds.length > 0 && (
        <p className="data-limits-note">
          {backtest.skippedRounds.length} round(s) skipped for missing data — declared in the ledger.
        </p>
      )}
    </section>
  );
}

/** The Model Gauntlet — You vs three models vs the ensemble, across played rounds. */
export function ModelsPage({ record }: ModelsPageProps) {
  const client = useEngineClient();
  const standings = seasonStandings(record);
  const played = playedRounds(record);
  const models = useResource(() => client.getModels(), []);
  const backtest = useResource(() => client.getBacktest(), []);

  return (
    <section className="gauntlet" aria-label="Model standings">
      <h1>Model Gauntlet</h1>
      <p className="screen-intro">
        Every round you play, all five of us get scored by the engine, the same way. Beat the ensemble — almost
        nobody does.
      </p>

      {played.length === 0 ? (
        <p className="empty-state">
          No rounds played yet. Call a race on the Race tab — the standings fill in as you go.
        </p>
      ) : (
        <table className="standings-table">
          <thead>
            <tr>
              <th scope="col">Competitor</th>
              <th scope="col">Pts</th>
              <th scope="col">Rounds</th>
              <th scope="col">Exact</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((entry) => (
              <tr key={entry.competitorId} className={entry.competitorId === "you" ? "is-you" : undefined}>
                <th scope="row">{COMPETITOR_NAMES[entry.competitorId]}</th>
                <td>{entry.points}</td>
                <td>{entry.roundsPlayed}</td>
                <td>{entry.exactHitRate == null ? "—" : `${Math.round(entry.exactHitRate * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ResourceView
        resource={backtest}
        context="Backtest accuracy"
        ready={(backtestRecord) =>
          backtestRecord == null ? (
            <p className="empty-state">
              No backtest record in the served ledger yet — run <code>make demo</code> to measure the models.
            </p>
          ) : (
            <BacktestPanel backtest={backtestRecord} />
          )
        }
      />

      <ResourceView
        resource={models}
        context="Model roster"
        ready={(view) => (
          <section aria-label="Model roster" className="model-roster">
            <h2>The grid</h2>
            <ul>
              {view.models.map((model) => (
                <li key={model.modelId}>
                  <strong>{model.modelId}</strong> — {model.method}. {model.role}
                  {model.consensusThreshold != null && <> Consensus threshold: {model.consensusThreshold}.</>}
                </li>
              ))}
            </ul>
          </section>
        )}
      />

      {played.length > 0 && (
        <section aria-label="Played rounds" className="round-flags">
          <h2>Consensus by round</h2>
          <ul>
            {played.map(({ raceKey, flag }) => (
              <li key={raceKey}>
                <span className="flag-round">{raceKey}</span>
                {flag ? <ConsensusChip flag={flag} coinFlip /> : <span className="empty-state">no verdict</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <AdvisoryBanner />
    </section>
  );
}
