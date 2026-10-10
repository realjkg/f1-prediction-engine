/**
 * Driver display identity — codes and names come from the pinned snapshot
 * via the generated directory (lib/driverDirectory.ts). A driverId missing
 * from the snapshot renders as its raw id rather than a fake name.
 */

import { DRIVERS } from "./driverDirectory";

/** Generated from data/snapshot/drivers.parquet — regenerated on data refresh. */
export interface DriverIdentity {
  driverId: string;
  code: string;
  name: string;
}

/** Full display name, falling back to the raw driver id. */
export function driverName(driverId: string): string {
  return DRIVERS[driverId]?.name ?? driverId;
}

/** Three-letter timing code, falling back to the raw driver id. */
export function driverCode(driverId: string): string {
  return DRIVERS[driverId]?.code ?? driverId;
}
