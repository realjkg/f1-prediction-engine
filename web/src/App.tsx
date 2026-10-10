import { useCallback, useEffect, useState } from "react";
import { BottomNav, ROUTES, type Route } from "./components/BottomNav";
import { BriefPage } from "./routes/BriefPage";
import { EvidencePage } from "./routes/EvidencePage";
import { ModelsPage } from "./routes/ModelsPage";
import { ObservabilityPage } from "./routes/ObservabilityPage";
import { RacePage } from "./routes/RacePage";
import { SettingsPage } from "./routes/SettingsPage";
import { CALL_SHEETS } from "./fixtures/callsheets";
import { RECORDS_BY_RACE_ID } from "./fixtures/records";
import { badgesForRound } from "./lib/badges";
import {
  browserStorage,
  clearRecord,
  emptyRecord,
  loadRecord,
  saveRecord,
} from "./lib/pitwall";
import { seasonStandings } from "./lib/standings";
import { scoreRound, streakExtends } from "./lib/scoring";
import type { PitWallRecord, RoundCall } from "./types";

function routeFromHash(): Route {
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES as readonly string[]).includes(candidate) ? (candidate as Route) : "race";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [record, setRecord] = useState<PitWallRecord>(() => loadRecord(browserStorage()));

  useEffect(() => {
    // Hash routing is a subscription to a non-React system (the URL).
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (next: Route) => {
    window.location.hash = `/${next}`;
    setRoute(next);
  };

  /**
   * Persist the call: record + streak + best streak + badge union, computed
   * with the same scoring mirror the engine serves (TODO(api-wiring): the
   * lock endpoint becomes authoritative — client keeps only the optimistic
   * copy).
   */
  const lockCall = useCallback((raceId: string, call: RoundCall) => {
    setRecord((current) => {
      const sheet = CALL_SHEETS[raceId];
      const predictionRecord = RECORDS_BY_RACE_ID[raceId];
      if (!sheet || !predictionRecord) {
        throw new Error(`Fixture inconsistency: no call sheet or prediction record for ${raceId}`);
      }
      const flag = predictionRecord.ensemble.consensus.flag;
      const score = scoreRound(call, sheet.finishingOrder, flag);
      const streakAfter = streakExtends(score) ? current.streak + 1 : 0;
      const base: PitWallRecord = {
        ...current,
        calls: { ...current.calls, [raceId]: call },
        streak: streakAfter,
        bestStreak: Math.max(current.bestStreak, streakAfter),
      };
      // Badge evaluation sees the record INCLUDING this round — standings
      // recomputed over `base` count this round's points.
      const standings = seasonStandings(base);
      const earned = badgesForRound({
        exactPodium: score.positionExactCount === 3,
        winnerCalled: score.winnerBonus,
        streakAfterRound: streakAfter,
        playerPoints: standings.find((entry) => entry.competitorId === "you")?.points ?? 0,
        ensemblePoints: standings.find((entry) => entry.competitorId === "ensemble")?.points ?? 0,
        winnerProb: predictionRecord.ensemble.winner[call.p1] ?? null,
        p2OnPodium: positionIn(sheet.finishingOrder, call.p2) <= 3,
        p3OnPodium: positionIn(sheet.finishingOrder, call.p3) <= 3,
        evidenceViews: base.evidenceViews,
      });
      const badges = [...new Set([...base.badges, ...earned])];
      const next: PitWallRecord = { ...base, badges };
      saveRecord(browserStorage(), next);
      return next;
    });
  }, []);

  const setProfileName = useCallback((profileName: string) => {
    setRecord((current) => {
      const next = { ...current, profileName };
      saveRecord(browserStorage(), next);
      return next;
    });
  }, []);

  const setFreshEyes = useCallback((freshEyes: boolean) => {
    setRecord((current) => {
      const next = { ...current, freshEyes };
      saveRecord(browserStorage(), next);
      return next;
    });
  }, []);

  const resetRecord = useCallback(() => {
    clearRecord(browserStorage());
    setRecord(emptyRecord());
  }, []);

  // Navigation only — the Evidence page counts its own visit on mount, so an
  // open-from-reveal is counted exactly once.
  const openEvidence = useCallback(() => {
    navigate("evidence");
  }, [navigate]);

  /** Counts the Evidence Room visit without navigating — used by the Evidence tab itself. */
  const countEvidenceView = useCallback(() => {
    setRecord((current) => {
      const next = { ...current, evidenceViews: current.evidenceViews + 1 };
      saveRecord(browserStorage(), next);
      return next;
    });
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Pit Wall</span>
        <span className="app-banner">ADVISORY ONLY — PINNED DATASET 2020–2024 — NO LIVE INFERENCE</span>
      </header>
      <main className="app-main">
        {route === "race" && <RacePage record={record} onLock={lockCall} onOpenEvidence={openEvidence} />}
        {route === "models" && <ModelsPage record={record} />}
        {route === "evidence" && <EvidencePage onView={countEvidenceView} />}
        {route === "brief" && <BriefPage />}
        {route === "observability" && <ObservabilityPage />}
        {route === "settings" && (
          <SettingsPage
            record={record}
            onProfileName={setProfileName}
            onFreshEyes={setFreshEyes}
            onReset={resetRecord}
          />
        )}
      </main>
      <BottomNav active={route} onNavigate={navigate} />
    </div>
  );
}

function positionIn(finishingOrder: string[], driverId: string): number {
  const index = finishingOrder.indexOf(driverId);
  return index < 0 ? Number.POSITIVE_INFINITY : index + 1;
}
