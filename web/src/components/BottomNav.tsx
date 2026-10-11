export const ROUTES = ["race", "live-lab", "models", "evidence", "brief", "observability", "supply-chain", "settings"] as const;

export type Route = (typeof ROUTES)[number];

export const ROUTE_LABELS: Record<Route, string> = {
  race: "Race",
  "live-lab": "Live Lab",
  models: "Models",
  evidence: "Evidence",
  brief: "Brief",
  observability: "Observability",
  settings: "Settings",
  "supply-chain": "Inventory",
};

interface BottomNavProps {
  active: Route;
  onNavigate: (route: Route) => void;
}

export function BottomNav({ active, onNavigate }: BottomNavProps) {
  return (
    <nav className="bottom-nav" aria-label="Primary">
      {ROUTES.map((route) => (
        <button
          key={route}
          type="button"
          className={route === active ? "nav-tab is-active" : "nav-tab"}
          aria-current={route === active ? "page" : undefined}
          onClick={() => onNavigate(route)}
        >
          {ROUTE_LABELS[route]}
        </button>
      ))}
    </nav>
  );
}
