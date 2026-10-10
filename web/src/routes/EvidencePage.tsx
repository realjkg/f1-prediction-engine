import { useEffect } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ResourceView } from "../components/EngineError";
import { ProbabilityBars } from "../components/ProbabilityBars";
import { isBacktestRecord, isPredictionRecord } from "../lib/calls";
import { useEngineClient, useResource } from "../lib/engine";
import type { BacktestRecord, LedgerRecord, PredictionRecord } from "../types";

interface EvidencePageProps {
  /** Counts the visit — Data Nerd opens the room five times. */
  onView: () => void;
}

const shortDigest = (sha: string): string => `${sha.slice(0, 12)}…`;

/** A served prediction record — the per-round evidence the reveals deep-link to. */
function PredictionLedgerCard({ record }: { record: PredictionRecord }) {
  return (
    <li className="ledger-record" data-prediction-id={record.predictionId}>
      <header className="ledger-head">
        <h2>{record.race.name}</h2>
        <ConsensusChip flag={record.ensemble.consensus.flag} coinFlip />
      </header>
      <p className="ledger-basis">{record.evidenceBasis}</p>
      <dl className="ledger-meta">
        <div>
          <dt>Dataset</dt>
          <dd>
            {record.dataset.id} · {shortDigest(record.dataset.sha256)}
          </dd>
        </div>
        <div>
          <dt>Generated</dt>
          <dd>{record.generatedAt.slice(0, 10)}</dd>
        </div>
        <div>
          <dt>Record digest</dt>
          <dd>{shortDigest(record.recordSha256)}</dd>
        </div>
        <div>
          <dt>Chain from</dt>
          <dd>{shortDigest(record.prevRecordSha256 ?? "0".repeat(64))}</dd>
        </div>
      </dl>

      <h3>Ensemble — winner</h3>
      <ProbabilityBars distribution={record.ensemble.winner} label={`${record.race.name} ensemble winner probabilities`} />
      <h3>Ensemble — podium</h3>
      <ProbabilityBars distribution={record.ensemble.podium} label={`${record.race.name} ensemble podium probabilities`} />

      <details className="ledger-models">
        <summary>Per-model breakdown</summary>
        {Object.entries(record.models).map(([modelId, model]) => (
          <div key={modelId} className="ledger-model">
            <h4>{modelId}</h4>
            <ProbabilityBars distribution={model.winner} label={`${modelId} winner probabilities`} />
          </div>
        ))}
      </details>

      <div className="ledger-limits">
        <h3>Declared limitations</h3>
        <ul>
          {record.dataLimitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </div>
      {record.advisoryOnly && <span className="advisory-tag">ADVISORY ONLY</span>}
    </li>
  );
}

/** A served backtest record — the measured-accuracy evidence. */
function BacktestLedgerCard({ record }: { record: BacktestRecord }) {
  return (
    <li className="ledger-record is-backtest" data-backtest-id={record.backtestId}>
      <header className="ledger-head">
        <h2>
          Backtest {record.season} — rounds {record.firstRound}–{record.lastRound}
        </h2>
        <span className="advisory-tag">MEASURED</span>
      </header>
      <p className="ledger-basis">{record.evidenceBasis}</p>
      <dl className="ledger-meta">
        <div>
          <dt>Dataset</dt>
          <dd>
            {record.dataset.id} · {shortDigest(record.dataset.sha256)}
          </dd>
        </div>
        <div>
          <dt>Rounds scored</dt>
          <dd>{record.roundsScored}</dd>
        </div>
        <div>
          <dt>Record digest</dt>
          <dd>{shortDigest(record.recordSha256)}</dd>
        </div>
      </dl>
      <table className="standings-table">
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Winner hit</th>
            <th scope="col">Podium@3</th>
            <th scope="col">Mean Brier</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(record.metrics).map(([modelId, metric]) => (
            <tr key={modelId}>
              <th scope="row">{modelId}</th>
              <td>{Math.round(metric.winnerHitRate * 100)}%</td>
              <td>{Math.round(metric.podium3HitRate * 100)}%</td>
              <td>{metric.meanBrier.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {record.dataLimitations.length > 0 && (
        <div className="ledger-limits">
          <h3>Declared limitations</h3>
          <ul>
            {record.dataLimitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
      {record.advisoryOnly && <span className="advisory-tag">ADVISORY ONLY</span>}
    </li>
  );
}

function LedgerRecordCard({ record }: { record: LedgerRecord }) {
  return isPredictionRecord(record) ? (
    <PredictionLedgerCard record={record} />
  ) : isBacktestRecord(record) ? (
    <BacktestLedgerCard record={record} />
  ) : null;
}

/** The Evidence Room — the hash-chained ledger, the credibility layer. */
export function EvidencePage({ onView }: EvidencePageProps) {
  const client = useEngineClient();
  const evidence = useResource(() => client.getEvidence(0, 25), []);

  useEffect(() => {
    onView();
  }, [onView]);

  return (
    <section className="evidence-room" aria-label="Evidence room">
      <h1>Evidence Room</h1>
      <p className="screen-intro">
        The engine's hash-chained ledger, served only while the chain verifies. Tampering with any record breaks every
        chain after it.
      </p>
      <AdvisoryBanner />

      <ResourceView
        resource={evidence}
        context="Evidence ledger"
        ready={(page) => (
          <>
            <p className="ledger-status">
              {page.records.length} of {page.total} records · chain valid: {page.chainValid ? "yes" : "NO"}
            </p>
            {page.records.length === 0 ? (
              <p className="empty-state">
                The ledger is empty — run <code>make demo</code> to generate predictions and the backtest.
              </p>
            ) : (
              <ul className="ledger">
                {page.records.map((record) => (
                  <LedgerRecordCard key={record.recordSha256} record={record} />
                ))}
              </ul>
            )}
          </>
        )}
      />
    </section>
  );
}
