/**
 * Typed client for the engine's read surface — the ONLY module in the web
 * app that speaks HTTP to the engine (web/vite.config.ts proxies /api in dev;
 * same-origin in prod, so baseUrl defaults to "").
 *
 * Fail-closed contract, mirroring the engine's typed errors: every failure is
 * an ApiError carrying the engine's error code (or a client-side one for
 * transport/parse failures) — never a thrown string, never a silent fallback,
 * never mock data substituting for a failed fetch. Response bodies are
 * structurally validated against the small set of invariants the screens
 * dereference (record type tags, view wrappers) so contract drift fails fast
 * as RESPONSE_INVALID instead of as an undefined-property render.
 *
 * Engine authority: the client NEVER computes scores, verifies hashes, or
 * invents consensus flags — all of that arrives from the engine
 * (GET /api/races/{raceId}/score?call=P1,P2,P3&streak_before=N serves the
 * engine-computed score with the ledger's consensus flag applied).
 */

import type {
  BacktestRecord,
  CallScore,
  ConfigView,
  EvidencePageView,
  EventsView,
  ModelsView,
  PredictionsView,
  RaceResultView,
  RacesView,
} from "../types";

/**
 * Every error the client can surface. Engine codes mirror app.py's typed
 * handlers; client codes cover the transport gap the engine cannot see.
 * `ENGINE_UNREACHABLE` is the "engine down" state the screens render with a
 * retry affordance.
 */
export type EngineErrorCode =
  // engine (app.py)
  | "RACE_UNKNOWN"
  | "RACE_AMBIGUOUS"
  | "RESULT_NOT_FOUND"
  | "PREDICTIONS_NOT_FOUND"
  | "CALL_MALFORMED"
  | "EVIDENCE_TAMPERED"
  | "EVIDENCE_CHAIN_GAP"
  | "EVIDENCE_SCHEMA_INVALID"
  | "EVIDENCE_RECORD_INVALID"
  // client (this module)
  | "ENGINE_UNREACHABLE"
  | "RESPONSE_INVALID"
  | "RESPONSE_NOT_OK";

export class ApiError extends Error {
  readonly code: EngineErrorCode;
  readonly status: number;

  constructor(code: EngineErrorCode, message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

/**
 * A wire code is only trusted when the client knows it — an unknown engine
 * code degrades to RESPONSE_NOT_OK with the code preserved in the message,
 * instead of a lying type cast.
 */
function knownErrorCode(code: string): EngineErrorCode {
  return isEngineErrorCode(code) ? code : "RESPONSE_NOT_OK";
}

/** Records the engine's `detail: {code, message}` body into an ApiError. */
function errorFromResponse(response: Response, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "object" && detail !== null && "code" in detail) {
    const parsed = detail as { code?: unknown; message?: unknown };
    if (typeof parsed.code === "string") {
      const message =
        typeof parsed.message === "string"
          ? parsed.message
          : `engine refused ${response.status} ${response.url}`;
      return new ApiError(knownErrorCode(parsed.code), message, response.status);
    }
  }
  return new ApiError(
    "RESPONSE_NOT_OK",
    `engine responded ${response.status} for ${response.url}`,
    response.status,
  );
}

/**
 * Minimal structural guard over the fields every consumer dereferences:
 * view wrappers must be objects with the expected collection field. Full
 * per-field validation stays in the engine (the contract's authority) — the
 * client refuses to render a structurally wrong envelope, not to re-validate
 * the payload.
 */
function assertShape(
  body: unknown,
  path: string,
  requiredKeys: readonly string[],
): void {
  if (typeof body !== "object" || body === null) {
    throw new ApiError("RESPONSE_INVALID", `${path} returned a non-object body`);
  }
  for (const key of requiredKeys) {
    if (!(key in (body as Record<string, unknown>))) {
      throw new ApiError(
        "RESPONSE_INVALID",
        `${path} response missing "${key}" — contract drift`,
      );
    }
  }
}

const ERROR_CODES = new Set<EngineErrorCode>([
  "RACE_UNKNOWN",
  "RACE_AMBIGUOUS",
  "RESULT_NOT_FOUND",
  "PREDICTIONS_NOT_FOUND",
  "CALL_MALFORMED",
  "EVIDENCE_TAMPERED",
  "EVIDENCE_CHAIN_GAP",
  "EVIDENCE_SCHEMA_INVALID",
  "EVIDENCE_RECORD_INVALID",
  "ENGINE_UNREACHABLE",
  "RESPONSE_INVALID",
  "RESPONSE_NOT_OK",
]);

/** Coerce an unknown throw into an ApiError — unknown throws become RESPONSE_INVALID. */
export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : String(error);
  return new ApiError("RESPONSE_INVALID", message);
}

/** The subset of the engine surface the screens consume. */
export interface EngineClient {
  getRaces(): Promise<RacesView>;
  /** Season-qualified — snapshot race ids repeat across seasons. */
  getPredictions(raceId: string, season: number): Promise<PredictionsView>;
  getRaceResult(raceId: string, season: number): Promise<RaceResultView>;
  /**
   * The engine-computed round score — consensus flag from the ledger
   * server-side, streak_before from the pit-wall record. The client never
   * scores locally.
   */
  getRaceScore(
    raceId: string,
    call: string[],
    streakBefore: number,
    season: number,
  ): Promise<CallScore>;
  getModels(): Promise<ModelsView>;
  getEvidence(offset: number, limit: number): Promise<EvidencePageView>;
  getEvents(): Promise<EventsView>;
  getConfig(): Promise<ConfigView>;
  getMetrics(): Promise<string>;
  /**
   * The ledger's backtest record — measured accuracy for the Gauntlet.
   * Null when the served ledger carries none yet (demo has not run backtest).
   */
  getBacktest(): Promise<BacktestRecord | null>;
}

/**
 * Backtest metrics read the ledger: GET /api/evidence carries the
 * BacktestRecord among the prediction records, and the engine has no
 * dedicated backtest endpoint. The client extracts it — display data only.
 */
export async function backtestFromPage(page: EvidencePageView): Promise<BacktestRecord | null> {
  for (const record of page.records) {
    if (record.recordType === "backtest") return record;
  }
  return null;
}

export function createEngineClient(
  fetchImpl: typeof fetch = (...args) => fetch(...args),
  baseUrl = "",
): EngineClient {
  async function getJson<T>(path: string, requiredKeys: readonly string[]): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        headers: { accept: "application/json" },
      });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      throw new ApiError(
        "ENGINE_UNREACHABLE",
        `the engine is unreachable at ${baseUrl}${path} — ${message}`,
      );
    }
    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        // Non-JSON error body — errorFromResponse degrades to RESPONSE_NOT_OK.
      }
      throw errorFromResponse(response, body);
    }
    let data: unknown;
    try {
      data = await response.json();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      throw new ApiError("RESPONSE_INVALID", `${path} returned invalid JSON — ${message}`);
    }
    assertShape(data, path, requiredKeys);
    return data as T;
  }

  const seasonQuery = (season: number): string => `season=${season}`;

  return {
    getRaces: () => getJson<RacesView>("/api/races", ["races", "total"]),
    getPredictions: (raceId, season) =>
      getJson<PredictionsView>(
        `/api/predictions/${encodeURIComponent(raceId)}?${seasonQuery(season)}`,
        ["predictions", "total"],
      ),
    getRaceResult: (raceId, season) =>
      getJson<RaceResultView>(
        `/api/races/${encodeURIComponent(raceId)}/result?${seasonQuery(season)}`,
        ["raceId", "classified"],
      ),
    getRaceScore: (raceId, call, streakBefore, season) =>
      getJson<CallScore>(
        `/api/races/${encodeURIComponent(raceId)}/score?call=${call.join(",")}` +
          `&streak_before=${streakBefore}&${seasonQuery(season)}`,
        ["round", "streak"],
      ),
    getModels: () => getJson<ModelsView>("/api/models", ["models"]),
    getEvidence: (offset, limit) =>
      getJson<EvidencePageView>(`/api/evidence?offset=${offset}&limit=${limit}`, [
        "records",
        "total",
        "chainValid",
      ]),
    getEvents: () => getJson<EventsView>("/api/events", ["events", "total"]),
    getConfig: () => getJson<ConfigView>("/api/config", ["engineVersion", "briefMode"]),
    getMetrics: async () => {
      const response = await fetchImpl(`${baseUrl}/metrics`, {
        headers: { accept: "text/plain" },
      });
      if (!response.ok) {
        throw new ApiError(
          "RESPONSE_NOT_OK",
          `metrics responded ${response.status}`,
          response.status,
        );
      }
      return response.text();
    },
    getBacktest: async () => {
      const page = await getJson<EvidencePageView>(
        `/api/evidence?offset=0&limit=100`,
        ["records", "total", "chainValid"],
      );
      return backtestFromPage(page);
    },
  };
}

/** Is this error code one of the engine's typed detail codes? */
export function isEngineErrorCode(code: string): code is EngineErrorCode {
  return ERROR_CODES.has(code as EngineErrorCode);
}

/** The default singleton — screens import hooks, not this. */
export const engineClient: EngineClient = createEngineClient();
