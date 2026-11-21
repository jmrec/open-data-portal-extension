import { bigint, pgSchema, varchar } from "drizzle-orm/pg-core";

export const beneco = pgSchema("beneco");

export const municipalities = beneco.table("municipalities", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  /** OCHA/HDX pcode, e.g. PH1401102. Kept for reference; use `psgc`. */
  pcode: varchar("pcode", { length: 25 }),
  psgc: varchar("psgc", { length: 10 }),
});

export const barangays = beneco.table("barangays", {
  id: bigint("id", { mode: "number" }).primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  municipalityId: bigint("municipality_id", { mode: "number" })
    .notNull()
    .references(() => municipalities.id),
  /** OCHA/HDX pcode, e.g. PH1401102142. Kept for reference; use `psgc`. */
  pcode: varchar("pcode", { length: 25 }),
  psgc: varchar("psgc", { length: 10 }),
});
