import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { raceById } from "../fixtures/races";
import { driverName } from "../fixtures/drivers";
import {
  COMPETITOR_NAMES,
  latestNearMiss,
  playedRounds,
  seasonStandings,
} from "../lib/standings";
import type { PitWallRecord } from "../types";

interface ModelsPageProps {
  record: PitWallRecord;
}

/** The Model Gauntlet — You vs three models vs the ensemble, across played rounds. */
export function ModelsPage({ record }: ModelsPageProps) {
  const standings = seasonStandings(record);
  const played = playedRounds(record);
  const miss = latestNearMiss(record);

  return (
    <section className="gauntlet" aria-label="Model standings">
      <h1>Model Gauntlet</h1>
      <p className="screen-intro">
        Every round you play, all five of us get scored the same way. Beat the ensemble — almost nobody does.
      </p>

      {played.length === 0 ? (
        <p className="empty-state">No rounds played yet. Call a race on the Race tab — the standings fill in as you go.</p>
      ) : (
        <>
          <table className="standings-table">
            <thead>
              <tr>
                <th scope="col">Competitor</th>
                <th scope="col">Pts</th>
                <th scope="col">Exact</th>
                <th scope="col">Brier</th>
              </tr>
            </thead>
            <tbody>
              {standings.map((entry) => (
                <tr key={entry.competitorId} className={entry.competitorId === "you" ? "is-you" : undefined}>
                  <th scope="row">{COMPETITOR_NAMES[entry.competitorId]}</th>
                  <td>{entry.points}</td>
                  <td>{entry.exactHitRate == null ? "—" : `${Math.round(entry.exactHitRate * 100)}%`}</td>
                  <td>{entry.meanBrier == null ? "—" : entry.meanBrier.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <section aria-label="Played rounds" className="round-flags">
            <h2>Consensus by round</h2>
            <ul>
              {played.map(({ raceId, flag }) => (
                <li key={raceId}>
                  <span className="flag-round">{raceById(raceId)?.name ?? raceId}</span>
                  <ConsensusChip flag={flag} coinFlip />
                </li>
              ))}
            </ul>
          </section>

          {miss && (
            <p className="near-miss" role="status">
              Last near miss: your P{miss.pickedSlot} {driverName(miss.driverId)} finished P4.
              {miss.ensembleKnew ? " The ensemble had him on its podium — it knew." : ""}
            </p>
          )}
        </>
      )}
      <AdvisoryBanner />
    </section>
  );
}
