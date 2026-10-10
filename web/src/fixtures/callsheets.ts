/**
 * Call-sheet fixture — what the player may see before locking a podium:
 * the qualifying grid, recent-form snapshot, and (for the reveal) the
 * classified finishing order.
 *
 * The call sheet is game UI over two engine sources: qualifying lines ride on
 * the brief contract's RaceDigest.qualifying (engine/f1engine/brief.py), and
 * the finishing order is the snapshot's classified result (GET /api/races/
 * {raceId}/result at wiring). TODO(api-wiring): replace this module's exports
 * with those fetches (task todo_gFifvtGU).
 */

import type { QualifyingLine } from "../types";

/** Recent finishes for one driver — most recent first, 3 entries. */
export interface FormLine {
  driverId: string;
  recentFinishes: number[];
}

export interface CallSheet {
  raceId: string;
  qualifying: QualifyingLine[];
  form: FormLine[];
  /**
   * Classified finishing order, position = index + 1. Carries the full pool
   * so near-miss (P4) scoring and reveal lookups never miss.
   */
  finishingOrder: string[];
}

/** Compact grid authoring: [driverId, qBestMs, deltaPoleMs] in grid order. */
type GridSpec = [string, number, number];

function grid(...spec: GridSpec[]): QualifyingLine[] {
  return spec.map(([driverId, qBestMs, deltaPoleMs], index) => ({
    driverId,
    position: index + 1,
    qBestMs,
    deltaPoleMs,
  }));
}

function form(...spec: [string, number[]][]): FormLine[] {
  return spec.map(([driverId, recentFinishes]) => ({ driverId, recentFinishes }));
}

export const CALL_SHEETS: Record<string, CallSheet> = {
  "austrian-gp": {
    raceId: "austrian-gp",
    qualifying: grid(
      ["77-bot", 891234, 0],
      ["1-max", 891567, 333],
      ["4-nor", 891890, 656],
      ["16-lec", 892123, 889],
      ["63-rus", 892456, 1222],
      ["55-sai", 892789, 1555],
      ["14-alo", 893012, 1778],
      ["44-ham", 894345, 3111],
      ["81-pia", 895678, 4444],
      ["27-hul", 896901, 5667],
    ),
    form: form(
      ["77-bot", [2, 1, 3]],
      ["44-ham", [1, 2, 1]],
      ["1-max", [5, 4, 2]],
      ["16-lec", [3, 6, 4]],
      ["4-nor", [6, 3, 5]],
      ["63-rus", [7, 9, 8]],
      ["55-sai", [9, 7, 10]],
      ["14-alo", [8, 5, 6]],
      ["81-pia", [10, 11, 9]],
      ["27-hul", [12, 8, 11]],
    ),
    // 2020 Austrian GP classified result: Bottas, Leclerc, Norris; Hamilton P4.
    finishingOrder: [
      "77-bot",
      "16-lec",
      "4-nor",
      "44-ham",
      "1-max",
      "55-sai",
      "63-rus",
      "81-pia",
      "14-alo",
      "27-hul",
    ],
  },
  "abu-dhabi-gp": {
    raceId: "abu-dhabi-gp",
    qualifying: grid(
      ["1-max", 822341, 0],
      ["44-ham", 822688, 347],
      ["55-sai", 823012, 671],
      ["10-gas", 823455, 1114],
      ["77-bot", 823899, 1558],
      ["16-lec", 824123, 1782],
      ["4-nor", 824566, 2225],
      ["63-rus", 825011, 2670],
      ["81-pia", 825678, 3337],
      ["27-hul", 826344, 4003],
    ),
    form: form(
      ["1-max", [1, 1, 2]],
      ["44-ham", [2, 1, 1]],
      ["55-sai", [3, 3, 3]],
      ["10-gas", [5, 6, 4]],
      ["77-bot", [6, 5, 7]],
      ["16-lec", [4, 8, 10]],
      ["4-nor", [7, 4, 6]],
      ["63-rus", [9, 7, 5]],
      ["81-pia", [8, 9, 11]],
      ["27-hul", [10, 12, 9]],
    ),
    // 2021 Abu Dhabi GP: Verstappen, Hamilton, Sainz; Gasly P4 — the coin-flip round.
    finishingOrder: [
      "1-max",
      "44-ham",
      "55-sai",
      "10-gas",
      "77-bot",
      "16-lec",
      "4-nor",
      "81-pia",
      "63-rus",
      "27-hul",
    ],
  },
  "saudi-arabian-gp": {
    raceId: "saudi-arabian-gp",
    qualifying: grid(
      ["16-lec", 871234, 0],
      ["1-max", 871567, 333],
      ["55-sai", 872012, 778],
      ["63-rus", 872456, 1222],
      ["44-ham", 872899, 1665],
      ["4-nor", 873123, 1889],
      ["11-per", 873566, 2332],
      ["14-alo", 874011, 2777],
      ["81-pia", 874678, 3444],
      ["27-hul", 875344, 4110],
    ),
    form: form(
      ["16-lec", [1, 2, 4]],
      ["1-max", [3, 1, 1]],
      ["55-sai", [2, 3, 5]],
      ["63-rus", [5, 4, 7]],
      ["44-ham", [4, 5, 3]],
      ["4-nor", [8, 6, 6]],
      ["11-per", [6, 8, 9]],
      ["14-alo", [7, 9, 8]],
      ["81-pia", [9, 10, 12]],
      ["27-hul", [11, 12, 10]],
    ),
    // 2022 Saudi Arabian GP: Verstappen, Sainz, Leclerc.
    finishingOrder: [
      "1-max",
      "55-sai",
      "16-lec",
      "63-rus",
      "44-ham",
      "4-nor",
      "11-per",
      "14-alo",
      "81-pia",
      "27-hul",
    ],
  },
  "bahrain-gp": {
    raceId: "bahrain-gp",
    qualifying: grid(
      ["1-max", 901234, 0],
      ["11-per", 901567, 333],
      ["16-lec", 902012, 778],
      ["55-sai", 902456, 1222],
      ["14-alo", 902899, 1665],
      ["44-ham", 903123, 1889],
      ["63-rus", 903566, 2332],
      ["4-nor", 904011, 2777],
      ["77-bot", 904678, 3444],
      ["27-hul", 905344, 4110],
    ),
    form: form(
      ["1-max", [1, 1, 1]],
      ["11-per", [2, 3, 2]],
      ["16-lec", [4, 2, 5]],
      ["55-sai", [5, 4, 3]],
      ["14-alo", [3, 7, 6]],
      ["44-ham", [6, 5, 4]],
      ["63-rus", [7, 6, 8]],
      ["4-nor", [9, 8, 7]],
      ["77-bot", [10, 9, 11]],
      ["27-hul", [8, 10, 12]],
    ),
    // 2023 Bahrain GP: Verstappen, Pérez, Alonso; Hamilton P4.
    finishingOrder: [
      "1-max",
      "11-per",
      "14-alo",
      "44-ham",
      "55-sai",
      "16-lec",
      "4-nor",
      "63-rus",
      "77-bot",
      "27-hul",
    ],
  },
  "british-gp": {
    raceId: "british-gp",
    qualifying: grid(
      ["63-rus", 882341, 0],
      ["44-ham", 882677, 336],
      ["4-nor", 882990, 649],
      ["1-max", 883345, 1004],
      ["81-pia", 883678, 1337],
      ["55-sai", 884012, 1671],
      ["14-alo", 884456, 2115],
      ["16-lec", 884901, 2560],
      ["11-per", 885566, 3225],
      ["27-hul", 886233, 3892],
    ),
    form: form(
      ["63-rus", [1, 3, 4]],
      ["44-ham", [3, 1, 2]],
      ["4-nor", [2, 3, 3]],
      ["1-max", [1, 1, 1]],
      ["81-pia", [4, 5, 6]],
      ["55-sai", [5, 6, 5]],
      ["14-alo", [7, 7, 7]],
      ["16-lec", [6, 4, 8]],
      ["11-per", [8, 9, 10]],
      ["27-hul", [10, 8, 9]],
    ),
    // 2024 British GP: Hamilton, Verstappen, Norris; Russell P4 — the upset the
    // models missed (they backed Verstappen).
    finishingOrder: [
      "44-ham",
      "1-max",
      "4-nor",
      "63-rus",
      "81-pia",
      "55-sai",
      "14-alo",
      "16-lec",
      "11-per",
      "27-hul",
    ],
  },
  "united-states-gp": {
    raceId: "united-states-gp",
    qualifying: grid(
      ["4-nor", 942341, 0],
      ["1-max", 942677, 336],
      ["63-rus", 943011, 670],
      ["55-sai", 943455, 1114],
      ["16-lec", 943899, 1558],
      ["44-ham", 944123, 1782],
      ["81-pia", 944566, 2225],
      ["14-alo", 945011, 2670],
      ["11-per", 945677, 3336],
      ["27-hul", 946344, 4003],
    ),
    form: form(
      ["4-nor", [2, 1, 3]],
      ["1-max", [1, 2, 1]],
      ["63-rus", [4, 3, 5]],
      ["55-sai", [3, 5, 4]],
      ["16-lec", [6, 4, 6]],
      ["44-ham", [5, 6, 7]],
      ["81-pia", [7, 8, 8]],
      ["14-alo", [9, 7, 9]],
      ["11-per", [10, 10, 10]],
      ["27-hul", [8, 11, 11]],
    ),
    // 2024 United States GP: Leclerc, Sainz, Verstappen; Norris P4.
    finishingOrder: [
      "16-lec",
      "55-sai",
      "1-max",
      "4-nor",
      "44-ham",
      "63-rus",
      "81-pia",
      "14-alo",
      "11-per",
      "27-hul",
    ],
  },
};

export function callSheetFor(raceId: string): CallSheet | undefined {
  return CALL_SHEETS[raceId];
}
