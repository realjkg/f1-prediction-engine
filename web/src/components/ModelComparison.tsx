import { formatPercent } from "../lib/baseline";
import { competitorColor } from "../lib/colors";
import { driverCode, driverName } from "../lib/drivers";
import type { PredictionRecord } from "../types";

interface ModelComparisonProps {
  record: PredictionRecord;
  /** How many drivers (rows) to compare, ranked by the ensemble's win probability. */
  count?: number;
}

const COLUMNS = ["m1-gbm", "m2-logit", "m3-form"] as const;

/**
 * Win probabilities side by side: drivers as rows, the three models and the
 * ensemble as columns, one shared 0-100% scale. Disagreement shows up as a row
 * whose bars differ in length, which a stack of separate cards hides.
 */
export function ModelComparison({ record, count = 5 }: ModelComparisonProps) {
  const rows = Object.entries(record.ensemble.winner)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, count)
    .map(([driverId, ensemble]) => ({
      driverId,
      values: {
        "m1-gbm": record.models["m1-gbm"]?.winner[driverId] ?? 0,
        "m2-logit": record.models["m2-logit"]?.winner[driverId] ?? 0,
        "m3-form": record.models["m3-form"]?.winner[driverId] ?? 0,
        ensemble,
      } as Record<(typeof COLUMNS)[number] | "ensemble", number>,
    }));
  if (rows.length === 0) return null;
  const columns = [...COLUMNS, "ensemble"] as const;

  return (
    <table className="comparison-table" aria-label={`${record.race.name} win probability by model`}>
      <thead>
        <tr>
          <th scope="col">Driver</th>
          {columns.map((column) => (
            <th key={column} scope="col" style={{ borderBottomColor: competitorColor(column) }}>
              {column === "ensemble" ? "Ensemble" : column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.driverId}>
            <th scope="row" title={driverName(row.driverId)}>
              {driverCode(row.driverId)}
            </th>
            {columns.map((column) => (
              <td key={column}>
                <span className="comparison-value num">{formatPercent(row.values[column])}</span>
                <span className="comparison-track" aria-hidden="true">
                  <span
                    className="comparison-fill"
                    style={{ width: `${Math.round(row.values[column] * 100)}%`, background: competitorColor(column) }}
                  />
                </span>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
