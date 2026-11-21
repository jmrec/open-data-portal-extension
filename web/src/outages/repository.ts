import { createHash } from "node:crypto";
import { inArray, notInArray, sql } from "drizzle-orm";
import { getDb } from "../db.ts";
import type {
  AreaResolution,
  AreaTask,
} from "../providers/beneco/area-types.ts";
import { resolvedOutages } from "./repository-schema.ts";

/**
 * Bump when the shape of a stored resolution changes, so every row is
 * resolved again once. psgc-1: areas carry 10-digit PSGC codes, not pcodes.
 */
const RESOLUTION_VERSION = "psgc-1";

export function fingerprintText(text: string): string {
  return createHash("sha256")
    .update(`${RESOLUTION_VERSION}\n${normalizeAreaText(text)}`)
    .digest("hex");
}

function normalizeAreaText(text: string): string {
  return text.trim().replace(/\r\n?/g, "\n");
}

export interface ResolutionRow {
  companyId: string;
  outageId: AreaTask["outageId"];
  kind: AreaTask["kind"];
  key: string;

  /** sha256 fingerprint of the normalized area text that produced this row. */
  fingerprint: string;

  resolution: AreaResolution;
  resolvedAt: Date;
}

export interface ResolutionWrite {
  companyId: string;
  outageId: AreaTask["outageId"];
  kind: AreaTask["kind"];
  key: string;
  fingerprint: string;
  resolution: AreaResolution;
}

export async function getResolvedOutageRows(
  companyId: string,
  outageIds: AreaTask["outageId"][],
): Promise<ResolutionRow[]> {
  if (outageIds.length === 0) return [];
  const storeDb = getDb();
  const rows = await storeDb
    .select()
    .from(resolvedOutages)
    .where(
      sql`${resolvedOutages.companyId} = ${companyId} and ${inArray(resolvedOutages.outageId, outageIds)}`,
    );
  return rows;
}

/** Insert or refresh stored resolutions for outages the resolver just ran on. */
export async function upsertResolvedOutageRows(
  rows: ResolutionWrite[],
): Promise<void> {
  if (rows.length === 0) return;
  const storeDb = getDb();
  await storeDb
    .insert(resolvedOutages)
    .values(
      rows.map((row) => ({
        outageId: row.outageId,
        companyId: row.companyId,
        kind: row.kind,
        key: row.key,
        fingerprint: row.fingerprint,
        resolution: row.resolution,
        resolvedAt: new Date(),
      })),
    )
    .onConflictDoUpdate({
      target: [resolvedOutages.companyId, resolvedOutages.outageId],
      set: {
        kind: sql`excluded.kind`,
        key: sql`excluded.key`,
        fingerprint: sql`excluded.fingerprint`,
        resolution: sql`excluded.resolution`,
        resolvedAt: sql`excluded.resolved_at`,
      },
    });
}

/**
 * Delete stored rows whose outage ids are no longer present in `liveOutageIds`.
 * Pass an empty array to clear the table entirely.
 */
export async function pruneResolvedOutages(
  companyId: string,
  liveOutageIds: AreaTask["outageId"][],
): Promise<void> {
  const storeDb = getDb();
  if (liveOutageIds.length === 0) {
    await storeDb
      .delete(resolvedOutages)
      .where(sql`${resolvedOutages.companyId} = ${companyId}`);
    return;
  }
  await storeDb
    .delete(resolvedOutages)
    .where(
      sql`${resolvedOutages.companyId} = ${companyId} and ${notInArray(resolvedOutages.outageId, liveOutageIds)}`,
    );
}
