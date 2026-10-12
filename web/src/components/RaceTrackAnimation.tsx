import { useState, type CSSProperties } from "react";
import "./RaceTrackAnimation.css";

interface RaceTrackAnimationProps {
  playedRounds: number;
  streak: number;
  badges: number;
}

const SHOW_CARS = [
  { id: "red", name: "Crimson", delay: 0, baseSeconds: 9 },
  { id: "teal", name: "Teal", delay: 2.4, baseSeconds: 10.5 },
  { id: "gold", name: "Gold", delay: 4.8, baseSeconds: 9.8 },
] as const;

/** Original, non-team-branded top-down open-wheel car artwork. */
function CarSilhouette() {
  return (
    <svg viewBox="0 0 112 48" aria-hidden="true" focusable="false">
      <rect x="17" y="3" width="19" height="11" rx="3" fill="#10151b" />
      <rect x="17" y="34" width="19" height="11" rx="3" fill="#10151b" />
      <rect x="78" y="3" width="21" height="11" rx="3" fill="#10151b" />
      <rect x="78" y="34" width="21" height="11" rx="3" fill="#10151b" />
      <path d="M7 18 L23 16 L36 19 L71 19 L81 13 L88 13 L91 20 L107 21 L107 27 L91 28 L88 35 L81 35 L71 29 L36 29 L23 32 L7 30 Z" fill="currentColor" stroke="#090d12" strokeWidth="2" />
      <path d="M25 13 V35 M90 17 V31" stroke="#e6edf5" strokeWidth="4" strokeLinecap="round" />
      <path d="M48 19 L65 19 L70 24 L65 29 L48 29 Z" fill="#10151b" stroke="#cdd8e2" strokeWidth="1.3" />
      <path d="M10 24 H27" stroke="white" strokeWidth="2" opacity="0.85" />
    </svg>
  );
}

function motionAllowedByPreference(): boolean {
  return typeof window.matchMedia !== "function" ||
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Visual-only warm-up race for the historical Replay game.
 * Car movement is never derived from or presented as timing/telemetry.
 */
export function RaceTrackAnimation({ playedRounds, streak, badges }: RaceTrackAnimationProps) {
  const [running, setRunning] = useState(motionAllowedByPreference);
  const [pace, setPace] = useState<1 | 2>(1);

  return (
    <section className="race-motion" aria-label="Race Rewind animated warm-up">
      <div className="race-motion__head">
        <div>
          <span className="race-motion__eyebrow">PIT WALL / RACE REWIND</span>
          <p className="race-motion__headline">Make the call. Chase the podium.</p>
        </div>
        <span className="race-motion__mode">ARCADE REPLAY</span>
      </div>
      <div className="race-motion__stage" data-motion={running ? "playing" : "paused"} data-speed={pace}>
        <div className="race-motion__start-line" aria-hidden="true" />
        <div className="race-motion__finish-line" aria-hidden="true" />
        <div className="race-motion__lanes" role="img" aria-label="Three stylized, fictional open-wheel cars moving across a decorative race circuit.">
          {SHOW_CARS.map((car) => (
            <div className="race-motion__lane" key={car.id}>
              <span className={"race-motion__car race-motion__car--" + car.id}
                style={{
                  animationDuration: String(car.baseSeconds / pace) + "s",
                  animationDelay: String(-car.delay / pace) + "s",
                  animationPlayState: running ? "running" : "paused",
                } as CSSProperties}>
                <CarSilhouette />
              </span>
            </div>
          ))}
        </div>
        <div className="race-motion__stage-caption" aria-hidden="true">START / FINISH</div>
      </div>
      <div className="race-motion__bottom">
        <div className="race-motion__controls">
          <button className="race-motion__control" type="button" onClick={() => setRunning((current) => !current)}>
            {running ? "Pause cars" : "Resume cars"}
          </button>
          <button className="race-motion__control" type="button" onClick={() => setPace((current) => current === 1 ? 2 : 1)}
            aria-label={"Change visual speed, currently " + pace + " times"}>
            {pace}× speed
          </button>
        </div>
        <div className="race-motion__stats" aria-label="Your Replay progress">
          <span><strong>{playedRounds}</strong> rounds</span>
          <span><strong>{streak}</strong> streak</span>
          <span><strong>{badges}</strong> badges</span>
        </div>
      </div>
      <p className="race-motion__disclaimer">
        Animated cars are decorative, not real positions. Choose a past Grand Prix below to predict the podium, reveal the actual finish, and earn points.
      </p>
    </section>
  );
}
