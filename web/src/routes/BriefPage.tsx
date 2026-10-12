import { useState, type FormEvent } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ResourceView } from "../components/EngineError";
import { ProbabilityBars } from "../components/ProbabilityBars";
import { isPredictionRecord, topPicks } from "../lib/calls";
import { useEngineClient, useResource, type Resource } from "../lib/engine";
import type { EngineClient } from "../lib/api";
import { driverName } from "../lib/drivers";
import { asApiError } from "../lib/api";
import type { ClaudeBriefView } from "../types";
import type { ConfigView, PredictionRecord, RaceSummary } from "../types";
import { raceKeyOf } from "../types";

/**
 * The Brief screen — a reading of the ensemble's served distributions for one
 * round. The engine exposes no HTTP brief endpoint, so this page renders the
 * digest the brief machinery would consume (top picks, consensus, pins) and
 * states its basis from the record and config — never a fixture narrative.
 */
export function BriefPage() {
  const client = useEngineClient();
  const catalog = useResource(() => client.getRaces(), []);
  // The ledger, not the catalog, says which rounds have a prediction record: the
  // catalog spans 2020-2024 but the demo ledger only covers the scored season.
  const ledger = useResource(() => client.getEvidence(0, 50), []);
  const config = useResource(() => client.getConfig(), []);

  return (
    <section className="brief" aria-label="Race brief">
      <h1>Race Brief</h1>
      <p className="screen-intro">
        What the ensemble would brief before the call — straight from the served prediction record. Advisory, labeled,
        and never part of the evidence hash chain.
      </p>
      <ResourceView
        resource={catalog}
        context="Race catalog"
        ready={(view) => (
          <ResourceView
            resource={ledger}
            context="Prediction ledger"
            ready={(page) => {
              const covered = new Set(
                page.records.filter(isPredictionRecord).map((record) =>
                  raceKeyOf(record.race.season, record.race.round, record.race.raceId),
                ),
              );
              const briefable = view.races.filter((race) =>
                covered.has(raceKeyOf(race.season, race.round, race.raceId)),
              );
              return <BriefForRound races={briefable} client={client} config={config} />;
            }}
          />
        )}
      />
    </section>
  );
}

interface BriefForRoundProps {
  races: RaceSummary[];
  client: EngineClient;
  config: Resource<ConfigView | null>;
}

function BriefForRound({ races, client, config }: BriefForRoundProps) {
  // Start on the most recent round that has a record, never on one that errors.
  const [pickedIndex, setPickedIndex] = useState(Math.max(0, races.length - 1));
  const race = races[pickedIndex] ?? null;
  const prediction = useResource(
    () => (race ? client.getPredictions(race.raceId, race.season) : Promise.resolve(null)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the race identity IS the dependency
    [race?.raceId, race?.season],
  );

  if (!race) {
    return (
      <p className="empty-state">
        No prediction records in the served ledger yet — run <code>make demo</code> to generate them.
      </p>
    );
  }

  return (
    <>
      <div className="brief-switcher" role="tablist" aria-label="Brief selection">
        {races.map((candidate, index) => (
          <button
            key={raceKeyOf(candidate.season, candidate.round, candidate.raceId)}
            type="button"
            role="tab"
            aria-selected={index === pickedIndex}
            className={`brief-tab${index === pickedIndex ? " is-active" : ""}`}
            onClick={() => setPickedIndex(index)}
          >
            {candidate.season} R{candidate.round}
          </button>
        ))}
      </div>

      <ResourceView
        resource={prediction}
        context="Prediction record"
        ready={(page) =>
          page == null || page.predictions.length === 0 ? (
            <p className="empty-state">No prediction record served for this round.</p>
          ) : (
            <BriefCard record={page.predictions[0]} config={config} />
          )
        }
      />
    </>
  );
}

interface BriefCardProps {
  record: PredictionRecord;
  config: Resource<ConfigView | null>;
}

/** All models train as-of the same round — take the max of their diagnostics. */
function trainedThrough(record: PredictionRecord): number | null {
  const rounds = Object.values(record.models).map((model) => model.diagnostics.trainedThroughRound);
  return rounds.length > 0 ? Math.max(...rounds) : null;
}

function BriefCard({ record, config }: BriefCardProps) {
  const flag = record.ensemble.consensus.flag;
  const winTop = topPicks(record.ensemble.winner, 3);
  const leader = winTop[0] ?? null;
  const mode = config.status === "ready" ? config.data?.briefMode ?? null : null;

  return (
    <article className="brief-card" aria-label={`Brief for ${record.race.name}`}>
      <AdvisoryBanner text={record.evidenceBasis} />
      {mode === "fixture" && <AdvisoryBanner text="DETERMINISTIC FIXTURE — NO LOCAL MODEL INFERENCE" tone="warning" />}
      {mode === "live" && <AdvisoryBanner text="LIVE OLLAMA BRIEF — DIGEST-PINNED · TEMPERATURE 0" />}

      <h2>
        {record.race.name} — {record.race.season} round {record.race.round}
      </h2>
      {leader && (
        <p className="brief-summary">
          The ensemble's win call: {driverName(leader.driverId)} at {Math.round(leader.probability * 100)}%. Trained
          through round {trainedThrough(record)} of the pinned dataset.
        </p>
      )}
      <p className="brief-note">
        <ConsensusChip flag={flag} coinFlip />
        {flag === "LOW_CONSENSUS"
          ? " The models disagree on the podium — treat every card as a coin toss the data cannot settle."
          : " The models broadly agree on the podium shape."}
      </p>

      <div className="brief-digest">
        <h3>What the ensemble sees</h3>
        <h4>Winner probability</h4>
        <ProbabilityBars distribution={record.ensemble.winner} label={`${record.race.name} ensemble winner probabilities`} />
        <h4>Podium probability</h4>
        <ProbabilityBars distribution={record.ensemble.podium} label={`${record.race.name} ensemble podium probabilities`} />
        <dl className="brief-pins" aria-label="Digest pins">
          <div>
            <dt>Dataset</dt>
            <dd>
              {record.dataset.id} · {record.dataset.sha256.slice(0, 12)}…
            </dd>
          </div>
          <div>
            <dt>Record digest</dt>
            <dd>{record.recordSha256.slice(0, 12)}…</dd>
          </div>
          {mode && (
            <div>
              <dt>Brief mode</dt>
              <dd>{mode}</dd>
            </div>
          )}
        </dl>
      </div>

      <ClaudeNarrative key={record.recordSha256} record={record} />
      <div className="ledger-limits">
        <h3>Declared limitations</h3>
        <ul>
          {record.dataLimitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </div>
      {record.advisoryOnly && <span className="advisory-tag">ADVISORY ONLY</span>}
    </article>
  );
}

/**
 * Optional operator-only Claude layer. The AI Gateway key is never sent to
 * React. An operator-scoped access token is held only in component memory,
 * never persisted in local storage, URLs, build assets or analytics.
 */
function ClaudeNarrative({ record }: { record: PredictionRecord }) {
  const client = useEngineClient();
  const [accessToken, setAccessToken] = useState("");
  const [result, setResult] = useState<ClaudeBriefView | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function requestNarrative(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResult(null);
    setStatus("loading");
    setErrorMessage("");
    try {
      const note = await client.getClaudeBrief(
        record.race.raceId, record.race.season, accessToken,
      );
      if (note.recordSha256 !== record.recordSha256 ||
          note.datasetSha256 !== record.dataset.sha256) {
        throw new Error("Claude response refers to different evidence; narrative refused.");
      }
      setResult(note);
      setStatus("idle");
    } catch (cause) {
      setErrorMessage(asApiError(cause).message);
      setStatus("error");
    } finally {
      // Operator access is not retained between requests.
      setAccessToken("");
    }
  }

  return (
    <section className="brief-digest" aria-label="Optional Claude race explanation">
      <h3>Claude evidence brief</h3>
      <p className="screen-intro">
        Optional, operator-only historical interpretation. Claude describes
        the frozen ensemble record; it cannot read live timing or change
        the model's probabilities. This feature is disabled until the backend
        AI Gateway and operator access are configured.
      </p>
      <form onSubmit={(event) => void requestNarrative(event)}>
        <label htmlFor="claude-demo-access">Operator demo access token</label>
        <input
          id="claude-demo-access"
          type="password"
          autoComplete="off"
          value={accessToken}
          onChange={(event) => setAccessToken(event.target.value)}
          minLength={24}
          required
          placeholder="Operator-only token"
        />
        <button
          type="submit"
          className="secondary-button"
          disabled={status === "loading" || accessToken.length < 24}
        >
          {status === "loading" ? "Checking evidence…" : "Explain with Claude"}
        </button>
      </form>
      {status === "error" && <p role="alert" className="advisory-banner is-warning">{errorMessage}</p>}
      {result && (
        <div className="brief-note" role="status">
          <strong>AI-generated explanation · historical replay</strong>
          <p>{result.text}</p>
          <small>
            Evidence: {result.recordSha256.slice(0, 12)} · Model: {result.model}
            <br />
            Narrative is not a live prediction or independently validated analysis.
          </small>
        </div>
      )}
    </section>
  );
}
