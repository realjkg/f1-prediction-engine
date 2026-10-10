import { useState } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ConsensusChip } from "../components/ConsensusChip";
import { ProbabilityBars } from "../components/ProbabilityBars";
import { BRIEFS } from "../fixtures/briefs";

const MODE_BANNERS = {
  fixture: "DETERMINISTIC FIXTURE — NO LOCAL MODEL INFERENCE",
  live: "LIVE OLLAMA BRIEF — DIGEST-PINNED · TEMPERATURE 0",
} as const;

const BRIEF_IDS = Object.keys(BRIEFS);

/** The Brief screen — advisory race narrative with explicit evidence-basis labeling. */
export function BriefPage() {
  const [selectedId, setSelectedId] = useState(BRIEF_IDS[0]);
  const brief = BRIEFS[selectedId];

  return (
    <section className="brief" aria-label="Race brief">
      <h1>Race Brief</h1>
      <p className="screen-intro">
        A narrative pass over the numbers — advisory, labeled, and never part of the evidence hash chain.
      </p>

      <div className="brief-switcher" role="tablist" aria-label="Brief selection">
        {BRIEF_IDS.map((raceId) => (
          <button
            key={raceId}
            type="button"
            role="tab"
            aria-selected={raceId === selectedId}
            className={`brief-tab${raceId === selectedId ? " is-active" : ""}`}
            onClick={() => setSelectedId(raceId)}
          >
            {BRIEFS[raceId].race.name}
          </button>
        ))}
      </div>

      {brief ? (
        <article className="brief-card" aria-label={`Brief for ${brief.race.name}`}>
          <AdvisoryBanner text={MODE_BANNERS[brief.mode]} tone={brief.mode === "fixture" ? "warning" : "default"} />
          <AdvisoryBanner text={brief.evidenceBasis} />

          <h2>{brief.content.headline}</h2>
          <p className="brief-summary">{brief.content.summary}</p>
          <ul className="brief-points">
            {brief.content.talkingPoints.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
          {brief.content.consensusNote && (
            <p className="brief-note">
              <ConsensusChip flag={brief.digest.consensus.flag} coinFlip /> {brief.content.consensusNote}
            </p>
          )}

          <div className="brief-digest">
            <h3>What the ensemble sees</h3>
            <h4>Winner probability</h4>
            <ProbabilityBars
              entries={brief.digest.ensembleWinnerTop.map(({ driverId, probability }) => ({ driverId, probability }))}
            />
            <h4>Podium probability</h4>
            <ProbabilityBars
              entries={brief.digest.ensemblePodiumTop.map(({ driverId, probability }) => ({ driverId, probability }))}
            />
          </div>

          {brief.pins ? (
            <dl className="brief-pins" aria-label="Digest pins">
              <div>
                <dt>Ollama model</dt>
                <dd>
                  {brief.pins.ollamaModel} · {brief.pins.ollamaModelDigest.slice(0, 12)}…
                </dd>
              </div>
              <div>
                <dt>Dataset digest</dt>
                <dd>{brief.pins.datasetDigest.slice(0, 12)}…</dd>
              </div>
              <div>
                <dt>Record digest</dt>
                <dd>{brief.pins.recordSha256.slice(0, 12)}…</dd>
              </div>
            </dl>
          ) : (
            <p className="brief-pins-empty">No digest pins — the fixture brief is generated, not model-served.</p>
          )}
        </article>
      ) : (
        <p className="empty-state">No brief generated for this round in the fixture set.</p>
      )}
    </section>
  );
}
