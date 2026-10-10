import { useState } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ResourceView } from "../components/EngineError";
import { ProbabilityBars } from "../components/ProbabilityBars";
import { topPicks } from "../lib/calls";
import { useEngineClient, useResource, type Resource } from "../lib/engine";
import type { EngineClient } from "../lib/api";
import { driverName } from "../lib/drivers";
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
        ready={(view) => <BriefForRound races={view.races} client={client} config={config} />}
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
  const [pickedIndex, setPickedIndex] = useState(0);
  const race = races[pickedIndex] ?? null;
  const prediction = useResource(
    () => (race ? client.getPredictions(race.raceId, race.season) : Promise.resolve(null)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the race identity IS the dependency
    [race?.raceId, race?.season],
  );

  if (!race) {
    return <p className="empty-state">No rounds in the catalog — run <code>make demo</code> first.</p>;
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
