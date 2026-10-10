import { useEffect } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ProbabilityBars } from "../components/ProbabilityBars";
import { RECORDS } from "../fixtures/records";

interface EvidencePageProps {
  /** Counts the visit — Data Nerd opens the room five times. */
  onView: () => void;
}

const shortDigest = (sha: string): string => `${sha.slice(0, 12)}…`;

/** The Evidence Room — the hash-chained ledger, the credibility layer. */
export function EvidencePage({ onView }: EvidencePageProps) {
  useEffect(() => {
    onView();
  }, [onView]);

  return (
    <section className="evidence-room" aria-label="Evidence room">
      <h1>Evidence Room</h1>
      <p className="screen-intro">
        One hash-chained ledger record per round. Tampering with any record breaks every chain after it.
      </p>
      <AdvisoryBanner />

      <ul className="ledger">
        {RECORDS.map((record) => (
          <li key={record.predictionId} className="ledger-record">
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
            <ProbabilityBars entries={Object.entries(record.ensemble.winner).map(([driverId, probability]) => ({ driverId, probability }))} />
            <h3>Ensemble — podium</h3>
            <ProbabilityBars entries={Object.entries(record.ensemble.podium).map(([driverId, probability]) => ({ driverId, probability }))} />

            <details className="ledger-models">
              <summary>Per-model breakdown</summary>
              {Object.entries(record.models).map(([modelId, model]) => (
                <div key={modelId} className="ledger-model">
                  <h4>{modelId}</h4>
                  <ProbabilityBars
                    entries={Object.entries(model.winner).map(([driverId, probability]) => ({ driverId, probability }))}
                  />
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
        ))}
      </ul>
    </section>
  );
}
