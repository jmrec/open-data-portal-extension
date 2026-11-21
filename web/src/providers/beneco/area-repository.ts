import { eq, sql } from "drizzle-orm";
import { getDb } from "../../db.ts";
import { barangays, municipalities } from "./area-schema.ts";

type Municipality = Pick<
  typeof municipalities.$inferSelect,
  "id" | "name" | "psgc"
>;
type Barangay = Pick<
  typeof barangays.$inferSelect,
  "id" | "name" | "psgc" | "municipalityId"
> & { municipality: string };

async function listMunicipalities(): Promise<Municipality[]> {
  const db = getDb();
  return await db
    .select({
      id: municipalities.id,
      name: municipalities.name,
      psgc: municipalities.psgc,
    })
    .from(municipalities)
    .orderBy(municipalities.name);
}

/** Best municipality match: exact (case-insensitive) first, then containment. */
async function findMunicipality(
  name: string,
): Promise<Municipality | undefined> {
  const db = getDb();
  const q = name.trim().toLowerCase();
  if (!q) return undefined;

  const cols = {
    id: municipalities.id,
    name: municipalities.name,
    psgc: municipalities.psgc,
  };

  const exact = await db
    .select(cols)
    .from(municipalities)
    .where(sql`lower(${municipalities.name}) = ${q}`)
    .limit(1);
  if (exact.length > 0) return exact[0];

  const contain = await db
    .select(cols)
    .from(municipalities)
    .where(
      sql`lower(${municipalities.name}) like ${`%${q}%`}
        or ${q} like '%' || lower(${municipalities.name}) || '%'`,
    )
    .orderBy(sql`length(${municipalities.name}) asc`)
    .limit(1);
  return contain.length > 0 ? contain[0] : undefined;
}

async function suggestMunicipalities(
  name: string,
  limit = 5,
): Promise<Municipality[]> {
  const db = getDb();
  const q = name.trim().toLowerCase();
  if (!q) return [];
  return await db
    .select({
      id: municipalities.id,
      name: municipalities.name,
      psgc: municipalities.psgc,
    })
    .from(municipalities)
    .where(
      sql`lower(${municipalities.name}) like ${`%${q}%`}
        or ${q} like '%' || lower(${municipalities.name}) || '%'`,
    )
    .orderBy(sql`length(${municipalities.name}) asc`)
    .limit(limit);
}

async function barangaysForMunicipality(
  municipalityId: number,
): Promise<Barangay[]> {
  const db = getDb();
  return await db
    .select({
      id: barangays.id,
      name: barangays.name,
      psgc: barangays.psgc,
      municipality: municipalities.name,
      municipalityId: municipalities.id,
    })
    .from(barangays)
    .innerJoin(municipalities, eq(municipalities.id, barangays.municipalityId))
    .where(eq(barangays.municipalityId, municipalityId))
    .orderBy(barangays.name);
}

export {
  listMunicipalities,
  findMunicipality,
  suggestMunicipalities,
  barangaysForMunicipality,
};
