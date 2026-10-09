import { useEffect, useState } from "react";
import { BottomNav, ROUTES, type Route } from "./components/BottomNav";
import { EvidencePage } from "./routes/EvidencePage";
import { ModelsPage } from "./routes/ModelsPage";
import { ObservabilityPage } from "./routes/ObservabilityPage";
import { RacePage } from "./routes/RacePage";
import { SettingsPage } from "./routes/SettingsPage";

function routeFromHash(): Route {
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES as readonly string[]).includes(candidate) ? (candidate as Route) : "race";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);

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

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">F1 Prediction Engine</span>
        <span className="app-banner">ADVISORY ONLY — PINNED DATASET 2020–2024 — NO LIVE INFERENCE</span>
      </header>
      <main className="app-main">
        {route === "race" && <RacePage />}
        {route === "models" && <ModelsPage />}
        {route === "evidence" && <EvidencePage />}
        {route === "observability" && <ObservabilityPage />}
        {route === "settings" && <SettingsPage />}
      </main>
      <BottomNav active={route} onNavigate={navigate} />
    </div>
  );
}
