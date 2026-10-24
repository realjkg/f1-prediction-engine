import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { ResourceView } from "../components/EngineError";
import { useEngineClient, useResource } from "../lib/engine";
import type { PitWallRecord } from "../types";

interface SettingsPageProps {
  record: PitWallRecord;
  /** Fresh Eyes (design doc §7): hide rounds already played. */
  onFreshEyes: (freshEyes: boolean) => void;
  /** Clears this visit's pit-wall record. */
  onReset: () => void;
}

/**
 * Settings — the engine's operating contract (dataset version, consensus
 * threshold, brief mode) read from GET /api/config, plus the local pit-wall
 * preferences. Nothing is hardcoded: every engine number on this screen is
 * served, never bundled.
 */
export function SettingsPage({ record, onFreshEyes, onReset }: SettingsPageProps) {
  const client = useEngineClient();
  const config = useResource(() => client.getConfig(), []);

  return (
    <section className="settings" aria-label="Settings">
      <h1>Settings</h1>
      <p className="screen-intro">The engine's operating contract and this visit's pit-wall preferences.</p>

      <ResourceView
        resource={config}
        context="Engine configuration"
        ready={(view) => (
          <section aria-label="Engine contract" className="settings-contract">
            <dl className="ledger-meta">
              <div>
                <dt>Engine version</dt>
                <dd>{view.engineVersion}</dd>
              </div>
              <div>
                <dt>Dataset version</dt>
                <dd>{view.datasetVersion}</dd>
              </div>
              <div>
                <dt>Consensus threshold</dt>
                <dd>{view.consensusThreshold}</dd>
              </div>
              <div>
                <dt>Brief mode</dt>
                <dd>{view.briefMode}</dd>
              </div>
              <div>
                <dt>Advisory notice</dt>
                <dd>{view.advisoryNotice}</dd>
              </div>
            </dl>
          </section>
        )}
      />

      <section aria-label="Pit wall preferences" className="settings-profile">
        <h2>Pit wall</h2>
        <label className="toggle">
          <input type="checkbox" checked={record.freshEyes} onChange={(event) => onFreshEyes(event.target.checked)} />
          Fresh Eyes — hide rounds you have already played
        </label>
        <p className="settings-note">For ages 8 and up: racing analysis and fictional points only. No bets, money, ads, chat, profiles, or prizes. Nothing here is saved: your calls, score and preferences last only until you reload the page.</p>
        <p className="settings-note">
          Fresh Eyes keeps your record intact; it only filters the race picker, so a second viewer calls played rounds
          without hindsight.
        </p>
        <button type="button" className="danger-button" onClick={onReset}>
          Reset pit-wall record
        </button>
      </section>

      <AdvisoryBanner />
    </section>
  );
}
