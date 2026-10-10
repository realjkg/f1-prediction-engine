/**
 * React bindings for the engine client: a client context (tests inject a
 * mocked-fetch client; the app uses the same-origin default), the app config
 * loaded once through it, and a data-loading hook with explicit
 * loading/ready/error states — the off-happy-path contract every screen
 * renders. Errors are ApiErrors (typed codes); the error UI offers retry.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { asApiError, engineClient, type ApiError, type EngineClient } from "./api";
import type { ConfigView } from "../types";

const EngineClientContext = createContext<EngineClient>(engineClient);
export const EngineClientProvider = EngineClientContext.Provider;

export function useEngineClient(): EngineClient {
  return useContext(EngineClientContext);
}

type ConfigResource =
  | { status: "loading" }
  | { status: "ready"; config: ConfigView }
  | { status: "error"; error: ApiError };

const ConfigContext = createContext<ConfigResource>({ status: "loading" });
export const ConfigProvider = ConfigContext.Provider;

/** The app's operating contract (GET /api/config), loaded once above App. */
export function useConfig(): ConfigResource {
  return useContext(ConfigContext);
}

/** Reads the config from context, failing loudly when it is not ready. */
export function useConfigReady(): ConfigView {
  const config = useConfig();
  if (config.status !== "ready") {
    throw new Error("config consumed before the engine responded — render order bug");
  }
  return config.config;
}

/** The engine's evidence-basis banner text for the current config. */
export function advisoryBasis(config: ConfigView): string {
  return config.briefMode === "live"
    ? "REAL MODELS — PINNED DATASET 2020–2024 — LIVE OLLAMA BRIEF (DIGEST-PINNED)"
    : "REAL MODELS — PINNED DATASET 2020–2024 — NO LIVE INFERENCE";
}

export type Resource<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: ApiError };

export type ResourceWithRetry<T> = Resource<T> & {
  /** Re-runs the load — the engine-unreachable state's affordance. */
  retry: () => void;
};

/**
 * Load one engine resource. `load` must be stable per logical request
 * (callers pass it through useMemo/useCallback or inline with deps); the
 * hook re-runs when deps or the retry counter change, and ignores responses
 * after unmount — a stale response never paints.
 */
export function useResource<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
): ResourceWithRetry<T> {
  const client = useEngineClient();
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  // The effect re-runs per deps/attempt; `load` is re-created by the caller
  // in step with the same deps, so it is intentionally not a dependency.
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    load()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", error: asApiError(error) });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt, client]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return useMemo(() => ({ ...state, retry }), [state, retry]);
}
