/**
 * Primary routes first (prediction product), then the separate research and
 * game screens. Live Lab and the Rewind game sit after a divider so they never
 * read as part of the prediction flow.
 */
export const PRIMARY_ROUTES = ["predict", "compare", "models", "evidence", "about"] as const;
export const SECONDARY_ROUTES = ["live-lab", "race", "brief", "observability", "supply-chain", "settings"] as const;
export const ROUTES = [...PRIMARY_ROUTES, ...SECONDARY_ROUTES] as const;

export type Route = (typeof ROUTES)[number];

export const ROUTE_LABELS: Record<Route, string> = {
  predict: "Predictions",
  compare: "Compare",
  models: "Performance",
  evidence: "Data & Evidence",
  about: "About",
  "live-lab": "Live Lab",
  race: "Rewind",
  brief: "Brief",
  observability: "Observability",
  "supply-chain": "Inventory",
  settings: "Settings",
};

interface BottomNavProps {
  active: Route;
  onNavigate: (route: Route) => void;
}

export function BottomNav({ active, onNavigate }: BottomNavProps) {
  const tab = (route: Route) => (
    <button
      key={route}
      type="button"
      className={route === active ? "nav-tab is-active" : "nav-tab"}
      aria-current={route === active ? "page" : undefined}
      onClick={() => onNavigate(route)}
    >
      {ROUTE_LABELS[route]}
    </button>
  );
  return (
    <nav className="bottom-nav" aria-label="Primary">
      {PRIMARY_ROUTES.map(tab)}
      <span className="nav-divider" aria-hidden="true" />
      {SECONDARY_ROUTES.map(tab)}
    </nav>
  );
}
