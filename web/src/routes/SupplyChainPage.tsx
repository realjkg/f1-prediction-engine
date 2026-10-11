import { useMemo, useState } from "react";
import { EngineErrorPanel, Loading } from "../components/EngineError";
import { useEngineClient, useResource } from "../lib/engine";
import type { SupplyChainComponent, SupplyChainView } from "../types";

/** Lockfile-sourced inventory, never a claim of a complete release SBOM. */
export function SupplyChainPage() {
  const client = useEngineClient();
  const view = useResource(() => client.getSupplyChain(), []);
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
      <ReleaseChecklist />
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

const GATES = [
  { name: "Dependency inventory", state: "In progress",
    detail: "Python/npm CycloneDX generator and CI artifact. Full deployed binary SBOM still required." },
  { name: "Code and supply-chain tests", state: "Must pass",
    detail: "Python, web, CodeQL, image tests, audits and mobile builds for the release SHA." },
  { name: "Secure communications", state: "Needs verification",
    detail: "TLS 1.3 configuration is coded; verify real ingress and MQTT handshakes." },
  { name: "Race-state accuracy", state: "Needs verification",
    detail: "Blind chronological calibration and licensed live-source coverage are not complete." },
  { name: "Age-appropriate experience", state: "Needs review",
    detail: "8+ informational use, no betting, ads, chat, real-money prizes or public profiles; complete privacy and store reviews." },
  { name: "Release provenance", state: "Not qualified",
    detail: "Image/mobile SBOMs, signature, provenance, rollback, observability and artifact retention must be attested." },
] as const;

function ReleaseChecklist() {
  return (
    <section className="supply-release" aria-label="Release capability checklist">
      <h2>Release 1.0 capability gates</h2>
      <p className="screen-intro">Tracked engineering requirements. These are not automatically verified deployment statuses.</p>
      <ul>
        {GATES.map((gate) => (
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
