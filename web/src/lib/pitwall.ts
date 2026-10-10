/**
 * Pit-wall record — the player's local game state. localStorage-backed.
 *
 * TODO(api-wiring): calls stay localStorage in Milestone 1 (no accounts); the
 * engine score endpoint (todo_gFifvtGU) later replaces the local scoring
 * mirror in lib/scoring.ts — the record shape already carries what that
 * endpoint needs ({raceId: {p1, p2, p3}}).
 */

import type { BadgeId, PitWallRecord, RoundCall } from "../types";

const STORAGE_KEY = "pitwall.record.v1";

const VALID_BADGES: BadgeId[] = [
  "first-exact-podium",
  "three-in-a-row",
  "beat-the-ensemble",
  "cold-read",
  "data-nerd",
  "perfect-round",
];

/** Empty record — used when nothing is stored (or storage is corrupt). */
export function emptyRecord(): PitWallRecord {
  return {
    profileName: "",
    calls: {},
    streak: 0,
    bestStreak: 0,
    badges: [],
    freshEyes: false,
    evidenceViews: 0,
  };
}

/**
 * Read the record; falls back to empty on missing or malformed JSON.
 * Storage corruption must never brick the app — degrade to a fresh record.
 */
export function loadRecord(storage: Storage | null): PitWallRecord {
  if (!storage) return emptyRecord();
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return emptyRecord();
    return hydrate(JSON.parse(raw));
  } catch {
    // Corrupt record — start clean rather than crash or silently drop writes.
    return emptyRecord();
  }
}

/**
 * Validate an unknown stored shape into a PitWallRecord. Unknown fields are
 * dropped; missing fields get defaults. Hand-rolled rather than zod to keep
 * the bundle lean — the shape is ours, not external.
 */
export function hydrate(parsed: unknown): PitWallRecord {
  const base = emptyRecord();
  if (typeof parsed !== "object" || parsed === null) return base;
  const raw = parsed as Record<string, unknown>;

  const calls: PitWallRecord["calls"] = {};
  if (typeof raw.calls === "object" && raw.calls !== null) {
    for (const [raceId, value] of Object.entries(
      raw.calls as Record<string, unknown>,
    )) {
      const call = hydrateCall(value);
      if (call) calls[raceId] = call;
    }
  }

  const badges: BadgeId[] = Array.isArray(raw.badges)
    ? raw.badges.filter((b): b is BadgeId => VALID_BADGES.includes(b as BadgeId))
    : [];

  return {
    profileName:
      typeof raw.profileName === "string" ? raw.profileName : base.profileName,
    calls,
    streak: typeof raw.streak === "number" ? raw.streak : 0,
    bestStreak: typeof raw.bestStreak === "number" ? raw.bestStreak : 0,
    badges,
    freshEyes: raw.freshEyes === true,
    evidenceViews: typeof raw.evidenceViews === "number" ? raw.evidenceViews : 0,
  };
}

function hydrateCall(value: unknown): RoundCall | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  const { p1, p2, p3 } = raw;
  if (typeof p1 !== "string" || typeof p2 !== "string" || typeof p3 !== "string") {
    return undefined;
  }
  const lockedAt = typeof raw.lockedAt === "string" ? raw.lockedAt : undefined;
  const datasetDigest =
    typeof raw.datasetDigest === "string" ? raw.datasetDigest : undefined;
  return { p1, p2, p3, lockedAt, datasetDigest };
}

/** Persist the record; storage failures are surfaced, never swallowed. */
export function saveRecord(storage: Storage | null, record: PitWallRecord): void {
  if (!storage) {
    throw new Error("STORAGE_UNAVAILABLE — cannot persist pit-wall record");
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(record));
}

/** Test seam: clear the stored record. */
export function clearRecord(storage: Storage | null): void {
  storage?.removeItem(STORAGE_KEY);
}

/**
 * Browser storage accessor. Environments without accessible localStorage
 * (SSR, privacy modes that throw) get a memory shim so the UI still runs —
 * those writes are lost on reload, which is the honest degradation.
 */
export function browserStorage(): Storage {
  try {
    if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
  } catch {
    // window.localStorage can throw in privacy modes — fall through.
  }
  return memoryStorage();
}

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => {
      map.delete(key);
    },
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
  };
}
