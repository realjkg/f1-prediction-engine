import { advisoryBasis, useConfig } from "../lib/engine";

interface AdvisoryBannerProps {
  /** Override text — defaults to the engine's evidence basis for the current brief mode. */
  text?: string;
  tone?: "default" | "warning";
}

const FALLBACK_BASIS = "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE";

/**
 * The evidence-basis strip — advisory labeling, always visible. The default
 * text comes from the engine's config (fixture vs live brief mode), never a
 * hardcoded constant in the screens.
 */
export function AdvisoryBanner({ text, tone = "default" }: AdvisoryBannerProps) {
  const config = useConfig();
  const basis = text ?? (config.status === "ready" ? advisoryBasis(config.config) : FALLBACK_BASIS);
  return (
    <div className={`advisory-banner${tone === "warning" ? " is-warning" : ""}`} role="note">
      {basis}
    </div>
  );
}
