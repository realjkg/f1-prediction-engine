import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { BottomNav, ROUTES, type Route } from "./components/BottomNav";
import { EngineErrorPanel, Loading } from "./components/EngineError";
import { BriefPage } from "./routes/BriefPage";
import { EvidencePage } from "./routes/EvidencePage";
import { ModelsPage } from "./routes/ModelsPage";
import { ObservabilityPage } from "./routes/ObservabilityPage";
import { RacePage } from "./routes/RacePage";
import { LiveLabPage } from "./routes/LiveLabPage";
import { SettingsPage } from "./routes/SettingsPage";
import { SupplyChainPage } from "./routes/SupplyChainPage";
import { engineClient, ApiError } from "./lib/api";
import {
  ConfigProvider,
  EngineClientProvider,
  LiveNowProvider,
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
import { LIVE_RACE_ID, LIVE_SEASON, isLive } from "./lib/live";
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

  // "Live" in the header means the feed for the default race is connected with a
  // fresh licensed checkpoint right now. Anything else, including an unreachable
  // status endpoint, reads "Not live". The last answer is kept between polls so
  // the label does not flicker.
  const [liveTick, setLiveTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setLiveTick((previous) => previous + 1), 30000);
    return () => clearInterval(id);
  }, []);
  const liveStatus = useResource(
    () => client.getLiveStatus(LIVE_RACE_ID, Number(LIVE_SEASON)),
    [liveTick],
  );
  const liveRef = useRef(false);
  if (liveStatus.status === "ready") liveRef.current = isLive(liveStatus.data);
  if (liveStatus.status === "error") liveRef.current = false;
  const liveNow = liveRef.current;

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
        <span className="app-banner">{advisoryBasis(config, liveNow)}</span>
        <span className="app-replay-chip num">
          {liveNow ? "Live feed connected" : "Replay of past races"} · dataset {config.datasetVersion}
        </span>
      </header>
      <LiveNowProvider value={liveNow}>
      <main className="app-main">
        {route === "race" && <RacePage record={record} onLock={lockCall} onOpenEvidence={openEvidence} onViewStandings={() => navigate("models")} />}
        {route === "live-lab" && <LiveLabPage />}
        {route === "models" && <ModelsPage record={record} />}
        {route === "evidence" && <EvidencePage onView={countEvidenceView} />}
        {route === "brief" && <BriefPage />}
        {route === "observability" && <ObservabilityPage />}
        {route === "supply-chain" && <SupplyChainPage />}
        {route === "settings" && (
          <SettingsPage
            record={record}
            onProfileName={setProfileName}
            onFreshEyes={setFreshEyes}
            onReset={resetRecord}
          />
        )}
      </main>
      </LiveNowProvider>
      <BottomNav active={route} onNavigate={navigate} />
    </div>
  );
}
