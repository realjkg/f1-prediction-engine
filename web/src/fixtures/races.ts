/**
 * Race catalog fixture — mirrors GET /api/races (engine RacesView).
 *
 * race_id values are globally unique across seasons (the engine's snapshot
 * guarantees the same, and the pit-wall record keys calls by raceId).
 */

import type { RaceSummary } from "../types";

export const RACES: RaceSummary[] = [
  {
    season: 2020,
    round: 1,
    raceId: "austrian-gp",
    name: "Austrian Grand Prix",
    date: "2020-07-05",
    completed: true,
  },
  {
    season: 2021,
    round: 21,
    raceId: "abu-dhabi-gp",
    name: "Abu Dhabi Grand Prix",
    date: "2021-12-12",
    completed: true,
  },
  {
    season: 2022,
    round: 2,
    raceId: "saudi-arabian-gp",
    name: "Saudi Arabian Grand Prix",
    date: "2022-03-27",
    completed: true,
  },
  {
    season: 2023,
    round: 1,
    raceId: "bahrain-gp",
    name: "Bahrain Grand Prix",
    date: "2023-03-05",
    completed: true,
  },
  {
    season: 2024,
    round: 12,
    raceId: "british-gp",
    name: "British Grand Prix",
    date: "2024-07-07",
    completed: true,
  },
  {
    season: 2024,
    round: 19,
    raceId: "united-states-gp",
    name: "United States Grand Prix",
    date: "2024-10-20",
    completed: true,
  },
];

/** Fixture view of GET /api/races. */
export function racesView() {
  return { races: RACES, total: RACES.length };
}

export function raceById(raceId: string): RaceSummary | undefined {
  return RACES.find((race) => race.raceId === raceId);
}
