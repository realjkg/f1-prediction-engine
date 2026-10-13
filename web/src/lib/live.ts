import type { LiveStatusView } from "../types";

/**
 * The one definition of "Live" in the app. Live means a licensed feed is
 * connected right now and a fresh checkpoint from it exists. Replays,
 * synthetic fixtures, stale checkpoints and unreachable status all read
 * "Not live".
 */
export function isLive(status: LiveStatusView | null | undefined): boolean {
  return (
    status != null &&
    status.feedState === "connected" &&
    status.evidenceState === "fresh-checkpoint" &&
    status.sourceType === "licensed-live"
  );
}

export const liveWord = (live: boolean): "LIVE" | "NOT LIVE" => (live ? "LIVE" : "NOT LIVE");

// Build-time defaults for the Live Lab and the header status. The container demo
// sets these to its synthetic race; ordinary builds keep the real-race defaults.
// Public values only, never secrets.
export const LIVE_RACE_ID = import.meta.env.VITE_LIVE_LAB_RACE?.trim() || "singapore";
export const LIVE_SEASON = import.meta.env.VITE_LIVE_LAB_SEASON?.trim() || "2026";
