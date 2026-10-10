import { useState } from "react";
import { AdvisoryBanner } from "../components/AdvisoryBanner";
import { configView } from "../fixtures/config";
import type { PitWallRecord } from "../types";

interface SettingsPageProps {
  record: PitWallRecord;
  onProfileName: (name: string) => void;
  onFreshEyes: (enabled: boolean) => void;
  onReset: () => void;
}

/** Settings — the pit-wall profile, Fresh Eyes, install status, advisory notice. */
export function SettingsPage({ record, onProfileName, onFreshEyes, onReset }: SettingsPageProps) {
  const config = configView();
  const [confirmingReset, setConfirmingReset] = useState(false);

  return (
    <section className="settings" aria-label="Settings">
      <h1>Settings</h1>

      <form className="settings-form" onSubmit={(event) => event.preventDefault()}>
        <label htmlFor="profile-name">Pit-wall name</label>
        <input
          id="profile-name"
          type="text"
          value={record.profileName}
          maxLength={24}
          onChange={(event) => onProfileName(event.target.value)}
        />

        <label htmlFor="fresh-eyes" className="toggle-row">
          <input
            id="fresh-eyes"
            type="checkbox"
            checked={record.freshEyes}
            onChange={(event) => onFreshEyes(event.target.checked)}
          />
          <span>
            Fresh Eyes — hide rounds you've already played, so replays stay honest.
          </span>
        </label>
      </form>

      <section className="settings-block" aria-label="Install status">
        <h2>Install</h2>
        <p id="install-status">
          Installable PWA — add Pit Wall to your phone's home screen from the browser menu. No store, no account.
        </p>
      </section>

      <section className="settings-block" aria-label="Pit-wall record">
        <h2>Your record</h2>
        <p>
          {record.profileName} · streak {record.streak} (best {record.bestStreak}) · {Object.keys(record.calls).length}{" "}
          rounds called
        </p>
        {confirmingReset ? (
          <p>
            <button type="button" className="danger-button" onClick={onReset}>
              Yes, wipe my pit-wall record
            </button>{" "}
            <button type="button" className="secondary-button" onClick={() => setConfirmingReset(false)}>
              Keep it
            </button>
          </p>
        ) : (
          <button type="button" className="danger-button" onClick={() => setConfirmingReset(true)}>
            Reset record
          </button>
        )}
      </section>

      <section className="settings-block" aria-label="About the data">
        <h2>The honest print</h2>
        <p className="advisory-notice">{config.advisoryNotice}</p>
        <p className="config-line">
          Engine {config.engineVersion} · dataset {config.datasetVersion} · consensus threshold{" "}
          {config.consensusThreshold} · brief mode {config.briefMode}
        </p>
      </section>

      <AdvisoryBanner />
    </section>
  );
}
