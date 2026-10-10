/**
 * The off-happy-path surfaces every screen shares: a quiet loading state and
 * a typed error panel. The error panel names the engine's error code, the
 * human meaning, and offers retry — the failure contract is rendered, never
 * papered over with stale or mock data.
 */

import type { ReactNode } from "react";
import type { ApiError } from "../lib/api";
import type { ResourceWithRetry } from "../lib/engine";

/** The human meaning of each failure class — the screen-level copy. */
function errorHeadline(error: ApiError): string {
  switch (error.code) {
    case "ENGINE_UNREACHABLE":
      return "The engine is unreachable. Start it with `make demo` (or `make serve`), then retry.";
    case "RACE_UNKNOWN":
      return "The engine has no race under that identity.";
    case "RACE_AMBIGUOUS":
      return "That race id repeats across seasons — the request needs its season.";
    case "RESULT_NOT_FOUND":
      return "No classified result for this round yet.";
    case "PREDICTIONS_NOT_FOUND":
      return "No prediction record for this round yet — run the demo to generate the ledger.";
    case "CALL_MALFORMED":
      return "The locked call was refused as malformed.";
    case "EVIDENCE_TAMPERED":
    case "EVIDENCE_CHAIN_GAP":
    case "EVIDENCE_SCHEMA_INVALID":
    case "EVIDENCE_RECORD_INVALID":
      return "The evidence ledger refused to serve records — the chain did not verify.";
    case "RESPONSE_NOT_OK":
      return "The engine answered with an error.";
    case "RESPONSE_INVALID":
      return "The engine's response did not match the contract.";
  }
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="engine-loading" role="status" aria-live="polite">
      <p className="engine-loading-label">Loading {label}…</p>
    </div>
  );
}

interface EngineErrorPanelProps {
  error: ApiError;
  onRetry: () => void;
  /** What was being loaded — grounds the message. */
  context?: string;
}

export function EngineErrorPanel({ error, onRetry, context }: EngineErrorPanelProps) {
  return (
    <div className="engine-error" role="alert" data-error-code={error.code}>
      <h2>{context ? `${context} — error` : "Engine error"}</h2>
      <p className="engine-error-headline">{errorHeadline(error)}</p>
      <p className="engine-error-detail">
        {error.code}
        {error.status > 0 ? ` · HTTP ${error.status}` : ""} — {error.message}
      </p>
      <button type="button" className="primary-button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

interface ResourceViewProps<T> {
  resource: ResourceWithRetry<T>;
  /** Grounds the loading/error copy. */
  context: string;
  /** Renders the ready state. */
  ready: (data: T) => ReactNode;
}

/** Loading / error / ready over one engine resource — every screen's frame. */
export function ResourceView<T>({ resource, context, ready }: ResourceViewProps<T>) {
  if (resource.status === "loading") return <Loading label={context} />;
  if (resource.status === "error") {
    return <EngineErrorPanel error={resource.error} onRetry={resource.retry} context={context} />;
  }
  return <>{ready(resource.data)}</>;
}
