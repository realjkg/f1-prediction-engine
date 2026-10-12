import { RaceTrackAnimation } from "./RaceTrackAnimation";
import { seasonStandings } from "../lib/standings";
import { raceKeyOf } from "../types";
import type { PitWallRecord, RaceSummary } from "../types";
import "./GameHub.css";

interface GameHubProps {
  record: PitWallRecord;
  races: RaceSummary[];
  onStart: (race: RaceSummary) => void;
  onViewStandings: () => void;
}

/** The playable home: every number is backed by the existing engine-scored record. */
export function GameHub({ record, races, onStart, onViewStandings }: GameHubProps) {
  const playedCount = Object.keys(record.calls).length;
  const available = [...races]
    .filter((race) => race.completed && !record.calls[raceKeyOf(race.season, race.round, race.raceId)])
    .sort((a, b) => b.season - a.season || a.round - b.round);
  const next = available[0] ?? null;
  const standings = seasonStandings(record);
  const player = standings.find((entry) => entry.competitorId === "you");
  const rival = standings.find((entry) => entry.competitorId === "ensemble");
  const playerPosition = playedCount > 0 ? standings.findIndex((entry) => entry.competitorId === "you") + 1 : null;
  const sprintProgress = playedCount % 3;

  return (
    <section className="game-hub" aria-label="Grand Prix Challenge game">
      <RaceTrackAnimation playedRounds={playedCount} streak={record.streak} badges={record.badges.length} />
      <div className="game-hub__card">
        <div className="game-hub__heading">
          <div>
            <p className="game-hub__eyebrow">SOLO RACE CHALLENGE · HISTORICAL REPLAY</p>
            <h1>Race the AI. Win the podium.</h1>
            <p className="game-hub__subhead">Pick the top three finishers, lock your call, then reveal the real result. Every round you compete against four prediction models.</p>
          </div>
          <span className="game-hub__level">LEVEL {Math.floor(playedCount / 3) + 1}</span>
        </div>
        <ol className="game-hub__how">
          <li><span>1</span> Pick three drivers</li>
          <li><span>2</span> Beat the clock</li>
          <li><span>3</span> Score against the AI</li>
        </ol>
        <div className="game-hub__scoreboard" aria-label="Your game scoreboard">
          <div><strong>{player?.points ?? 0}</strong><span>Your points</span></div>
          <div><strong>{rival?.points ?? 0}</strong><span>AI ensemble</span></div>
          <div><strong>{playerPosition === null ? "—" : "#" + playerPosition}</strong><span>Place of five</span></div>
        </div>
        <div className="game-hub__mission">
          <div className="game-hub__mission-head">
            <span>3-round sprint</span>
            <span>{sprintProgress}/3 rounds</span>
          </div>
          <progress max={3} value={sprintProgress} aria-label="Current sprint progress" />
          <p>Complete three rounds, build a streak and climb the model standings. Points are for fun and never represent a financial stake.</p>
        </div>
        {next ? (
          <button type="button" className="primary-button game-hub__play" onClick={() => onStart(next)} aria-label="START CHALLENGE" aria-describedby="game-hub-next-race">
            START CHALLENGE <span aria-hidden="true">→</span>
            <small id="game-hub-next-race">{next.season} · {next.name}</small>
          </button>
        ) : (
          <div className="game-hub__complete" role="status">All completed rounds in this catalog have been played. Browse completed challenges below or review your standings.</div>
        )}
        <button type="button" className="secondary-button game-hub__standings" onClick={onViewStandings}>
          View AI rivals &amp; leaderboard
        </button>
      </div>
    </section>
  );
}
