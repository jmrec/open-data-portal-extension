import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const municipalities = sqliteTable("beneco_municipalities", {
  id: integer("id").primaryKey(),
  name: text("name").notNull(),
  /** OCHA/HDX pcode, e.g. PH1401102. Kept for reference; use `psgc`. */
  pcode: text("pcode"),
  psgc: text("psgc"),
});

export const barangays = sqliteTable("beneco_barangays", {
  id: integer("id").primaryKey(),
  name: text("name").notNull(),
  municipalityId: integer("municipality_id")
    .notNull()
    .references(() => municipalities.id),
  /** OCHA/HDX pcode, e.g. PH1401102142. Kept for reference; use `psgc`. */
  pcode: text("pcode"),
  psgc: text("psgc"),
});
