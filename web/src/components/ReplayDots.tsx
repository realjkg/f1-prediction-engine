import { driverCode } from "../lib/drivers";
import { replayStrip, replaySummary, winnerNote } from "../lib/replay";

interface ReplayDotsProps {
  /** A win distribution — driverId -> probability. */
  distribution: Record<string, number>;
  /** The driver who actually won, when known (reveal screens), to mark that group. */
  actualWinnerId?: string;
}

/**
 * "If this race ran 20 times…" — one dot per imagined replay, grouped by
 * driver. Identity rides on the printed driver code and count, so the groups
 * stay readable without color; the shade only helps the eye separate them.
 */
export function ReplayDots({ distribution, actualWinnerId }: ReplayDotsProps) {
  const strip = replayStrip(distribution);
  if (strip.groups.length === 0) return null;
  // An upset winner can round to zero dots; say where they fell rather than omit them.
  const note = winnerNote(strip, actualWinnerId);
  const spoken = replaySummary(strip, driverCode) + (note && actualWinnerId ? ` The actual winner, ${driverCode(actualWinnerId)}, won in ${note.text}.` : "");
  return (
    <figure className="replay" aria-label={spoken}>
      <figcaption className="replay-caption">If this race ran {strip.runs} times…</figcaption>
      <ul className="replay-groups" aria-hidden="true">
        {strip.groups.map((group, index) => (
          <li
            key={group.driverId}
            className={`replay-group is-shade-${index % 4}${group.driverId === actualWinnerId ? " is-actual" : ""}`}
          >
            <span className="replay-dots">
              {Array.from({ length: group.dots }, (_, dot) => (
                <span key={dot} className="replay-dot" />
              ))}
            </span>
            <span className="replay-label num">
              {driverCode(group.driverId)} {group.dots}
              {group.driverId === actualWinnerId ? " ★" : ""}
            </span>
          </li>
        ))}
        {strip.otherDots > 0 && (
          <li className="replay-group is-others">
            <span className="replay-dots">
              {Array.from({ length: strip.otherDots }, (_, dot) => (
                <span key={dot} className="replay-dot" />
              ))}
            </span>
            <span className="replay-label num">Others {strip.otherDots}</span>
          </li>
        )}
      </ul>
      {note && actualWinnerId && (
        <p className="replay-winner-note is-actual" aria-hidden="true">
          ★ Actual winner {driverCode(actualWinnerId)}: won in {note.text}
        </p>
      )}
    </figure>
  );
}
