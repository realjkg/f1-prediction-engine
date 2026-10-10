import { REAL_MODELS_EVIDENCE_BASIS } from "../fixtures/drivers";

interface AdvisoryBannerProps {
  /** Override text — defaults to the pinned-dataset evidence basis. */
  text?: string;
  tone?: "default" | "warning";
}

/** The evidence-basis strip — advisory labeling, always visible. */
export function AdvisoryBanner({ text = REAL_MODELS_EVIDENCE_BASIS, tone = "default" }: AdvisoryBannerProps) {
  return (
    <div className={`advisory-banner${tone === "warning" ? " is-warning" : ""}`} role="note">
      {text}
    </div>
  );
}
