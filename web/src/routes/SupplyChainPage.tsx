import { useMemo, useState } from "react";
import { EngineErrorPanel, Loading } from "../components/EngineError";
import { useEngineClient, useResource } from "../lib/engine";
import type { SupplyChainComponent, SupplyChainView } from "../types";

/** Lockfile-sourced inventory, never a claim of a complete release SBOM. */
export function SupplyChainPage() {
  const client = useEngineClient();
  const view = useResource(() => client.getSupplyChain(), []);
  // A valid research accuracy report is evidence of a completed evaluation,
  // not evidence that the in-race forecast is calibrated or releasable.
  const accuracy = useResource(() => client.getInraceAccuracy(), []);
  const [term, setTerm] = useState("");
  const [ecosystem, setEcosystem] = useState<"all" | "pypi" | "npm">("all");

  return (
    <section className="supply-chain" aria-label="Software supply chain inventory">
      <h1>Software inventory & release checks</h1>
      <p className="screen-intro">
        CycloneDX dependency inventory based on pinned Python and npm packages.
        A lockfile inventory is not a complete SBOM for deployed containers,
        mobile applications, or third-party services.
      </p>
      {view.status === "loading" && <Loading label="Verified software inventory" />}
      {view.status === "error" && (
        <div role="status">
          <EngineErrorPanel
            context="Software inventory" error={view.error} onRetry={view.retry}
          />
          <p className="screen-intro">
            The inventory is unavailable until its generated artifact and matching
            lockfiles are installed on the engine. No package list is invented.
          </p>
        </div>
      )}
      {view.status === "ready" && (
        <InventoryDetails
          inventory={view.data}
          query={term}
          onQuery={setTerm}
          ecosystem={ecosystem}
          onEcosystem={setEcosystem}
        />
      )}
      <ReleaseChecklist
        inventoryVerified={view.status === "ready"}
        accuracyEvidencePresent={accuracy.status === "ready"}
      />
    </section>
  );
}

function InventoryDetails({
  inventory, query, onQuery, ecosystem, onEcosystem,
}: {
  inventory: SupplyChainView;
  query: string;
  onQuery: (value: string) => void;
  ecosystem: "all" | "pypi" | "npm";
  onEcosystem: (value: "all" | "pypi" | "npm") => void;
}) {
  const matches = useMemo(
    () => inventory.components.filter((c) =>
      (ecosystem === "all" || c.ecosystem === ecosystem) &&
      `${c.name} ${c.version} ${c.license ?? ""}`.toLowerCase().includes(query.toLowerCase())
    ),
    [ecosystem, inventory.components, query],
  );
  return (
    <section className="supply-panel">
      <div className="supply-summary">
        <div><strong>{inventory.totalComponents}</strong><span>Locked packages</span></div>
        <div><strong>{inventory.ecosystemCounts.pypi ?? 0}</strong><span>Python</span></div>
        <div><strong>{inventory.ecosystemCounts.npm ?? 0}</strong><span>npm</span></div>
      </div>
      <p className="advisory-banner is-warning">
        Partial SBOM · Not release-attested · Production promotion remains gated.
      </p>
      <p className="supply-hash">
        CycloneDX {inventory.specVersion} · SHA-256
        <code>{inventory.sbomSha256}</code>
      </p>
      <div className="supply-controls">
        <label htmlFor="package-filter">Find a package
          <input id="package-filter" type="search" value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Package, version, license" />
        </label>
        <label htmlFor="ecosystem-filter">Ecosystem
          <select id="ecosystem-filter" value={ecosystem}
            onChange={(e) => onEcosystem(e.target.value as "all" | "pypi" | "npm")}>
            <option value="all">All</option>
            <option value="pypi">Python</option>
            <option value="npm">npm</option>
          </select>
        </label>
      </div>
      <p className="screen-intro" role="status">
        Showing {matches.length} of {inventory.totalComponents} packages.
      </p>
      <div className="supply-table-wrap">
        <table className="standings-table">
          <thead><tr><th scope="col">Component</th><th scope="col">Version</th>
            <th scope="col">Scope</th><th scope="col">License</th></tr></thead>
          <tbody>
            {matches.slice(0, 100).map((c: SupplyChainComponent, index) => (
              <tr key={`${c.ecosystem}-${c.name}-${c.version}-${index}`}>
                <th scope="row">{c.name}<small> {c.ecosystem}</small></th>
                <td>{c.version}</td><td>{c.scope}</td><td>{c.license ?? "Unknown"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {matches.length > 100 && (
        <p className="screen-intro">Showing the first 100 matches. Refine the search to see the rest.</p>
      )}
      <h2>Coverage limitations</h2>
      <ul className="supply-limitations">
        {inventory.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
      </ul>
      <h2>Lockfile provenance</h2>
      <dl className="supply-locks">
        {Object.entries(inventory.sourceDigests).sort().map(([path, digest]) => (
          <div key={path}><dt>{path}</dt><dd><code>{digest}</code></dd></div>
        ))}
      </dl>
    </section>
  );
}

interface Gate {
  name: string;
  state: string;
  detail: string;
}

function releaseGates(inventoryVerified: boolean, accuracyEvidencePresent: boolean): Gate[] {
  return [
    {
      name: "Runtime dependency inventory",
      state: inventoryVerified ? "Verified — partial SBOM" : "Unavailable",
      detail: inventoryVerified
        ? "The running engine serves a SHA-256-checked CycloneDX 1.6 inventory tied to its three lockfiles. Container OS and native mobile binaries are not covered."
        : "The engine has not supplied a verifiable CycloneDX artifact. Check container build, source lockfiles, or integrity manifest.",
    },
    {
      name: "Build and security checks",
      state: "Requires release-SHA CI evidence",
      detail: "Verify Python, web, dependency audit, CodeQL, TLS 1.3 container, mobile build and image checks against the same release commit. The UI does not have a signed CI attestation.",
    },
    {
      name: "TLS 1.3 end-to-end",
      state: "External endpoint verification required",
      detail: "Secure Docker ingress and backend mutual TLS have smoke tests. Real public deployment certificates, MQTT broker handshake and monitoring must be verified independently.",
    },
    {
      name: "Chronological race prediction accuracy",
      state: accuracyEvidencePresent ? "Research report available — not qualified" : "No verified evaluation report",
      detail: accuracyEvidencePresent
        ? "The server can supply a hash-verified research evaluation, but independent live-source coverage, calibration, and prospective improvement over the current-leader baseline are still required."
        : "There is no configured verified forward evaluation report. No live race-winner accuracy or calibrated probabilities may be claimed.",
    },
    {
      name: "Source and data rights",
      state: "External approval required",
      detail: "Document commercial and redistribution rights for licensed OpenF1 MQTT streams and historical race outcomes. Keep provider access tokens backend-only.",
    },
    {
      name: "Release identity and rollback",
      state: "Blocked",
      detail: "Produce container and native package SBOMs, bind them to signed image/app digests, attest deployment configuration, verify recovery, rollback, privacy and store-review evidence.",
    },
  ];
}

function ReleaseChecklist({
  inventoryVerified,
  accuracyEvidencePresent,
}: {
  inventoryVerified: boolean;
  accuracyEvidencePresent: boolean;
}) {
  const gates = releaseGates(inventoryVerified, accuracyEvidencePresent);
  return (
    <section className="supply-release" aria-label="Release capability checklist">
      <h2>Release capability gates</h2>
      <p className="advisory-banner is-warning" role="status">
        Production live prediction: NOT QUALIFIED. The statuses distinguish
        verified runtime evidence from external approvals and missing artifacts.
      </p>
      <ul>
        {gates.map((gate) => (
          <li key={gate.name}>
            <strong>{gate.name}</strong>
            <span className="supply-gate-state">{gate.state}</span>
            <p>{gate.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
