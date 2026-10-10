import { useCallback, useEffect, useState, type ReactNode } from "react";
import { BottomNav, ROUTES, type Route } from "./components/BottomNav";
import { EngineErrorPanel, Loading } from "./components/EngineError";
import { BriefPage } from "./routes/BriefPage";
import { EvidencePage } from "./routes/EvidencePage";
import { ModelsPage } from "./routes/ModelsPage";
import { ObservabilityPage } from "./routes/ObservabilityPage";
import { RacePage } from "./routes/RacePage";
import { SettingsPage } from "./routes/SettingsPage";
import { engineClient, ApiError } from "./lib/api";
import {
  ConfigProvider,
  EngineClientProvider,
  useConfigReady,
  useEngineClient,
  useResource,
  advisoryBasis,
} from "./lib/engine";
import {
  applyLockedRound,
  browserStorage,
  clearRecord,
  emptyRecord,
  loadRecord,
  saveRecord,
} from "./lib/pitwall";
import { summarizeRoundScore } from "./lib/calls";
import { COMPETITORS, callForCompetitor, type RoundCompetitorScores } from "./lib/standings";
import type {
  CallScore,
  LockOutcome,
  PitWallRecord,
  PredictionRecord,
  RaceIdentity,
  RaceKey,
  RoundCall,
} from "./types";
import { raceKeyOf } from "./types";

function routeFromHash(): Route {
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES as readonly string[]).includes(candidate) ? (candidate as Route) : "race";
}

export default function App() {
  return (
    <EngineClientProvider value={engineClient}>
      <EngineConfigGate>
        <Shell />
      </EngineConfigGate>
    </EngineClientProvider>
  );
}

/**
 * The engine's operating contract gates the whole app: nothing renders —
 * not even a picker — until GET /api/config answers, and a dead engine is
 * the typed error surface with retry, never stale or mock data.
 */
function EngineConfigGate({ children }: { children: ReactNode }) {
  const client = useEngineClient();
  const config = useResource(() => client.getConfig(), []);

  if (config.status === "loading") {
    return <Loading label="Engine configuration" />;
  }
  if (config.status === "error") {
    return (
      <EngineErrorPanel
        error={config.error}
        onRetry={config.retry}
        context="Engine configuration"
      />
    );
  }
  return <ConfigProvider value={{ status: "ready", config: config.data }}>{children}</ConfigProvider>;
}

function Shell() {
  const client = useEngineClient();
  const config = useConfigReady();
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
   * The lock: ask the ENGINE to score the player's call and each
   * competitor's podium call (consensus flag comes from the ledger
   * server-side; streak_before from the local record), then fold the
   * responses into the pit-wall record. Atomic — any failed score call
   * fails the lock and nothing is stored.
   */
  const lockCall = useCallback(
    async (
      race: RaceIdentity,
      call: RoundCall,
      predictionRecord: PredictionRecord,
    ): Promise<LockOutcome> => {
      const raceKey: RaceKey = raceKeyOf(race.season, race.round, race.raceId);
      const scores = {} as RoundCompetitorScores;
      let playerScore: CallScore | null = null;
      for (const competitor of COMPETITORS) {
        const competitorCall = callForCompetitor(predictionRecord, competitor, call);
        if (!competitorCall) {
          throw new ApiError(
            "RESPONSE_INVALID",
            `no podium call derivable for ${competitor} — the record's distribution has fewer than three drivers`,
          );
        }
        const score = await client.getRaceScore(
          race.raceId,
          [competitorCall.p1, competitorCall.p2, competitorCall.p3],
          competitor === "you" ? record.streak : 0,
          race.season,
        );
        scores[competitor] = summarizeRoundScore(score.round);
        if (competitor === "you") playerScore = score;
      }
      if (playerScore == null) {
        throw new ApiError("RESPONSE_INVALID", "the engine never scored the player's call");
      }

      const next = applyLockedRound(record, raceKey, call, scores, playerScore, predictionRecord);
      saveRecord(browserStorage(), next);
      const badgesEarned = next.badges.filter((badge) => !record.badges.includes(badge));
      setRecord(next);
      return { score: playerScore, badgesEarned };
    },
    [client, record],
  );

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
        <span className="app-banner">{advisoryBasis(config)}</span>
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
