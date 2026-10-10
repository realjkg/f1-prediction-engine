import type { PitWallRecord, RaceSummary } from "../types";
import { raceKeyOf } from "../types";

interface RacePickerProps {
  races: RaceSummary[];
  record: PitWallRecord;
  onPick: (race: RaceSummary) => void;
}

/**
 * Season-grouped round tiles — the engine's race catalog, completed rounds
 * only. Fresh Eyes (on by default) hides rounds the record has already
 * scored; played tiles surface the round again when the filter is off.
 */
export function RacePicker({ races, record, onPick }: RacePickerProps) {
  const seasons = [...new Set(races.map((race) => race.season))].sort((a, b) => b - a);
  const played = (race: RaceSummary) =>
    record.calls[raceKeyOf(race.season, race.round, race.raceId)] != null;
  const visible = record.freshEyes ? races.filter((race) => !played(race)) : races;

  if (visible.length === 0) {
    return (
      <section className="race-picker" aria-label="Round picker">
        <h1>Pick a round</h1>
        <p className="empty-state">
          Every round is played with Fresh Eyes on. Turn it off in Settings to replay them.
        </p>
      </section>
    );
  }

  return (
    <section className="race-picker" aria-label="Round picker">
      <h1>Pick a round</h1>
      {seasons.map((season) => {
        const seasonRaces = visible.filter((race) => race.season === season);
        if (seasonRaces.length === 0) return null;
        return (
          <div key={season} className="season-group">
            <h2>{season}</h2>
            <ul className="race-tiles">
              {seasonRaces.map((race) => (
                <li key={`${race.season}-r${race.round}-${race.raceId}`}>
                  <RaceTile race={race} played={played(race)} onPick={onPick} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

function RaceTile({
  race,
  played,
  onPick,
}: {
  race: RaceSummary;
  played: boolean;
  onPick: (race: RaceSummary) => void;
}) {
  return (
    <button type="button" className="race-tile" onClick={() => onPick(race)}>
      <span className="tile-round">R{race.round}</span>
      <span className="tile-name">{race.name}</span>
      <span className="tile-date">{race.date}</span>
      {played && <span className="tile-played">PLAYED</span>}
    </button>
  );
}
