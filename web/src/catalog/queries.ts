import { and, asc, desc, eq, inArray, sql } from "drizzle-orm";
import type { NodeSQLiteDatabase } from "drizzle-orm/node-sqlite";
import {
  type AdminLevel,
  adminLevelOf,
  CATALOG_LEVEL,
  LEVEL_IDS,
} from "./levels.ts";
import { datasets, lineage, placeCounts, places, rows } from "./schema.ts";

type Db = NodeSQLiteDatabase;

export interface DatasetInfo {
  name: string;
  description: string | null;
  attribution: string | null;
  license: string | null;
  url: string | null;
  rows: number;
  auto: number;
  needsReview: number;
  noPlace: number;
}

export interface PlaceRef {
  code: string;
  name: string;
  level: AdminLevel;
}

export type Json =
  | string
  | number
  | boolean
  | null
  | Json[]
  | { [key: string]: Json };

export type SourceRow = { [column: string]: Json };

export interface PlaceDataset {
  dataset: DatasetInfo;
  rows: number;
  /** Source columns of the first rows, as the export wrote them. */
  sample: SourceRow[];
}

export interface PlaceChild extends PlaceRef {
  rows: number;
}

export interface PlaceDetail extends PlaceRef {
  /** Coarsest first: region, province, city. */
  ancestors: PlaceRef[];
  datasets: PlaceDataset[];
  /** Places one level down, busiest first. */
  children: PlaceChild[];
}

/** Rows per place at `level`, as [code, rows] pairs, for one dataset or all. */
export async function placeCounts_(
  db: Db,
  level: AdminLevel,
  dataset?: string,
): Promise<[string, number][]> {
  const where = and(
    eq(placeCounts.level, CATALOG_LEVEL[level]),
    dataset ? eq(placeCounts.dataset, dataset) : undefined,
  );
  const result = await db
    .select({
      code: placeCounts.code,
      rows: sql<number>`sum(${placeCounts.rows})`,
    })
    .from(placeCounts)
    .where(where)
    .groupBy(placeCounts.code);
  return result.map((r) => [r.code, Number(r.rows)]);
}

export async function listDatasets(db: Db): Promise<DatasetInfo[]> {
  return db.select().from(datasets).orderBy(asc(datasets.name));
}

const LINEAGE_COLUMN = {
  barangay: lineage.barangay,
  city: lineage.cityMunicipality,
  province: lineage.province,
  region: lineage.region,
} as const;

export async function placeDetail(
  db: Db,
  code: string,
  sampleSize = 10,
): Promise<PlaceDetail | null> {
  const [place] = await db.select().from(places).where(eq(places.code, code));
  const level = place && adminLevelOf(place.level);
  if (!place || !level) return null;

  const [line] = await db.select().from(lineage).where(eq(lineage.code, code));
  const ancestorCodes = LEVEL_IDS.slice(0, LEVEL_IDS.indexOf(level))
    .map((id) => line?.[lineageKey(id)])
    .filter((c): c is string => Boolean(c));
  const named = ancestorCodes.length
    ? await db.select().from(places).where(inArray(places.code, ancestorCodes))
    : [];
  const ancestors = ancestorCodes.flatMap((c) => {
    const p = named.find((n) => n.code === c);
    const l = p && adminLevelOf(p.level);
    return p && l ? [{ code: p.code, name: p.name, level: l }] : [];
  });

  const counted = await db
    .select({ dataset: datasets, rows: placeCounts.rows })
    .from(placeCounts)
    .innerJoin(datasets, eq(datasets.name, placeCounts.dataset))
    .where(eq(placeCounts.code, code))
    .orderBy(desc(placeCounts.rows));
  const within = db
    .select({ code: lineage.code })
    .from(lineage)
    .where(eq(LINEAGE_COLUMN[level], code));
  const withSamples = await Promise.all(
    counted.map(async ({ dataset, rows: n }) => {
      const sample = await db
        .select({ data: rows.data })
        .from(rows)
        .where(and(eq(rows.dataset, dataset.name), inArray(rows.code, within)))
        .orderBy(asc(rows.rowId))
        .limit(sampleSize);
      return { dataset, rows: n, sample: sample.map((s) => s.data) };
    }),
  );

  const childLevel = LEVEL_IDS[LEVEL_IDS.indexOf(level) + 1];
  const children = childLevel
    ? (
        await db
          .select({
            code: places.code,
            name: places.name,
            rows: sql<number>`coalesce(sum(${placeCounts.rows}), 0)`,
          })
          .from(places)
          .leftJoin(placeCounts, eq(placeCounts.code, places.code))
          .where(
            and(
              eq(places.parentCode, code),
              eq(places.level, CATALOG_LEVEL[childLevel]),
            ),
          )
          .groupBy(places.code, places.name)
          .orderBy(desc(sql`3`), asc(places.name))
      ).map((c) => ({ ...c, rows: Number(c.rows), level: childLevel }))
    : [];

  return {
    code: place.code,
    name: place.name,
    level,
    ancestors,
    datasets: withSamples,
    children,
  };
}

function lineageKey(level: AdminLevel) {
  return level === "city" ? "cityMunicipality" : level;
}
