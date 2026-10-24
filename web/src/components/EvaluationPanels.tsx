import { useEngineClient, useResource } from "../lib/engine";
import { formatPercent } from "../lib/baseline";
import type { MetricEstimate } from "../types";
import { ResourceView } from "./EngineError";

const fixed = (value: number, digits = 2) => value.toFixed(digits);
const range = (metric: MetricEstimate, format: (value: number) => string) =>
  `${format(metric.ciLow)} to ${format(metric.ciHigh)}`;

/** Executed walk-forward evaluation: hit rate, log loss, Brier with intervals. */
export function ModelEvaluationPanel() {
  const client = useEngineClient();
  const evaluation = useResource(() => client.getModelEvaluation(), []);
  return (
    <section className="evaluation" aria-labelledby="evaluation-title">
      <h2 id="evaluation-title">How well the winner predictions held up</h2>
      <ResourceView
        resource={evaluation}
        context="Model evaluation"
        ready={(view) => (
          <>
            <p className="data-note">{view.method} Cohort: {view.cohort} ({view.rounds} races).</p>
            <div className="table-scroll"><table className="win-table">
              <caption>Lower log loss and Brier score are better. Ranges are 95% bootstrap intervals over races.</caption>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Winner picked</th>
                  <th scope="col">Log loss</th>
                  <th scope="col">Brier score</th>
                  <th scope="col" className="col-team">Avg. chance given to the winner</th>
                </tr>
              </thead>
              <tbody>
                {[...view.scores, view.baseline].map((score) => (
                  <tr key={score.modelId} className={score.modelId === "blind-guess" ? "baseline-row" : undefined}>
                    <th scope="row">{score.modelId === "blind-guess" ? "Blind guess (baseline)" : score.modelId}</th>
                    <td className="num">
                      {formatPercent(score.winnerHitRate.value)}
                      <span className="ci"> ({range(score.winnerHitRate, formatPercent)})</span>
                    </td>
                    <td className="num">
                      {fixed(score.winnerLogLoss.value)}
                      <span className="ci"> ({range(score.winnerLogLoss, (v) => fixed(v))})</span>
                    </td>
                    <td className="num">
                      {fixed(score.winnerBrier.value)}
                      <span className="ci"> ({range(score.winnerBrier, (v) => fixed(v))})</span>
                    </td>
                    <td className="num col-team">{formatPercent(score.meanProbabilityOnWinner)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <h3>Calibration ({view.calibrationModel})</h3>
            <p className="data-note">{view.calibrationVerdict}</p>
            <div className="table-scroll"><table className="win-table">
              <caption>When the model said a driver had this chance, how often that driver actually won</caption>
              <thead>
                <tr><th scope="col">Predicted chance</th><th scope="col">Predictions</th><th scope="col">Average predicted</th><th scope="col">Actually won</th></tr>
              </thead>
              <tbody>
                {view.calibration.map((bin) => (
                  <tr key={bin.lower}>
                    <th scope="row">{formatPercent(bin.lower)} to {formatPercent(bin.upper)}</th>
                    <td className="num">{bin.predictions}</td>
                    <td className="num">{bin.meanPredicted === null ? "—" : formatPercent(bin.meanPredicted)}</td>
                    <td className="num">{bin.observedWinRate === null ? "—" : formatPercent(bin.observedWinRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <ul className="limit-list">{view.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
          </>
        )}
      />
    </section>
  );
}

const SEVERITY_LABEL = { info: "OK", warning: "Warning", error: "Error" } as const;

/** Data-quality profile: coverage per season and each check's outcome. */
export function DataQualityPanel() {
  const client = useEngineClient();
  const report = useResource(() => client.getDataQuality(), []);
  return (
    <section className="data-quality" aria-labelledby="quality-title">
      <h2 id="quality-title">Data quality</h2>
      <ResourceView
        resource={report}
        context="Data quality"
        ready={(view) => (
          <>
            <p className={view.inferenceBlocked || view.trainingBlocked ? "advisory-banner is-warning" : "data-note"}>
              {view.summary} The data covers races through {view.dataThroughDate}; it was retrieved{" "}
              {view.sourceUpdatedAt.slice(0, 10)} ({view.sourceAgeDays} days ago).
            </p>
            <div className="table-scroll"><table className="win-table">
              <caption>Coverage by season</caption>
              <thead>
                <tr><th scope="col">Season</th><th scope="col">Races</th><th scope="col">With results</th><th scope="col">With qualifying</th><th scope="col">Predictions</th></tr>
              </thead>
              <tbody>
                {view.coverage.map((row) => (
                  <tr key={row.season}>
                    <th scope="row">{row.season}</th>
                    <td className="num">{row.races}</td>
                    <td className="num">{row.roundsWithResults}</td>
                    <td className="num">{row.roundsWithQualifying}</td>
                    <td className="num">{row.predictionRecords}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <ul className="check-list">
              {view.findings.map((finding) => (
                <li key={finding.check} className={finding.passed ? "is-pass" : "is-fail"}>
                  <span className="check-state">{finding.passed ? "Passed" : "Failed"}</span>{" "}
                  <span className={`severity severity-${finding.severity}`}>{SEVERITY_LABEL[finding.severity]}</span>{" "}
                  <strong>{finding.check}</strong>
                  {finding.affected > 0 ? ` (${finding.affected} affected)` : ""}
                  {finding.blocksInference ? " · blocks predictions" : ""}
                  {finding.blocksTraining ? " · blocks training" : ""}
                  <span className="check-detail"> {finding.detail}</span>
                  {finding.examples.length > 0 && (
                    <span className="check-detail"> Examples: {finding.examples.join("; ")}.</span>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      />
    </section>
  );
}
