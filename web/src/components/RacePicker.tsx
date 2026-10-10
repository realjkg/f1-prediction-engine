import type { PitWallRecord, RaceSummary } from "../types";
import { RACES } from "../fixtures/races";

interface RacePickerProps {
  record: PitWallRecord;
  onPick: (raceId: string) => void;
}

/** Season-grouped round tiles — completed 2020–2024 rounds only. */
export function RacePicker({ record, onPick }: RacePickerProps) {
  const seasons = [...new Set(RACES.map((race) => race.season))].sort((a, b) => b - a);
  const visible = record.freshEyes
    ? RACES.filter((race) => !record.calls[race.raceId])
    : RACES;

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
                <li key={race.raceId}>
                  <RaceTile race={race} played={record.calls[race.raceId] != null} onPick={onPick} />
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
  onPick: (raceId: string) => void;
}) {
  return (
    <button type="button" className="race-tile" onClick={() => onPick(race.raceId)}>
      <span className="tile-round">
        R{race.round}
      </span>
      <span className="tile-name">{race.name}</span>
      <span className="tile-date">{race.date}</span>
      {played && <span className="tile-played">PLAYED</span>}
    </button>
  );
}
