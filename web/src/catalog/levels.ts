/** Map levels, coarsest first, with the catalog's name for each. */
export const LEVEL_IDS = ["region", "province", "city", "barangay"] as const;

export type AdminLevel = (typeof LEVEL_IDS)[number];

export const CATALOG_LEVEL = {
  region: "region",
  province: "province",
  city: "city_municipality",
  barangay: "barangay",
} as const satisfies Record<AdminLevel, string>;

export type CatalogLevel = (typeof CATALOG_LEVEL)[AdminLevel];

export function adminLevelOf(level: string): AdminLevel | null {
  for (const id of LEVEL_IDS) if (CATALOG_LEVEL[id] === level) return id;
  return null;
}
