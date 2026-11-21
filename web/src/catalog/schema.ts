// Tables of data/output/catalog.sqlite, written by `just export`
// (src/open_data_portal_extension/catalog.py). The web app only reads them.
import {
  integer,
  primaryKey,
  real,
  sqliteTable,
  text,
} from "drizzle-orm/sqlite-core";
import type { SourceRow } from "./queries.ts";

export const datasets = sqliteTable("datasets", {
  name: text("name").primaryKey(),
  description: text("description"),
  attribution: text("attribution"),
  license: text("license"),
  url: text("url"),
  rows: integer("rows").notNull(),
  auto: integer("auto").notNull(),
  needsReview: integer("needs_review").notNull(),
  noPlace: integer("no_place").notNull(),
});

export const places = sqliteTable("places", {
  code: text("code").primaryKey(),
  name: text("name").notNull(),
  level: text("level").notNull(),
  parentCode: text("parent_code"),
});

export const lineage = sqliteTable("lineage", {
  code: text("code").primaryKey(),
  barangay: text("barangay"),
  cityMunicipality: text("city_municipality"),
  province: text("province"),
  region: text("region"),
});

export const placeCounts = sqliteTable(
  "place_counts",
  {
    dataset: text("dataset").notNull(),
    code: text("code").notNull(),
    level: text("level").notNull(),
    rows: integer("rows").notNull(),
  },
  (table) => [primaryKey({ columns: [table.dataset, table.code] })],
);

export const rows = sqliteTable(
  "rows",
  {
    dataset: text("dataset").notNull(),
    rowId: integer("row_id").notNull(),
    code: text("code").notNull(),
    confidence: real("confidence"),
    data: text("data", { mode: "json" }).$type<SourceRow>().notNull(),
  },
  (table) => [primaryKey({ columns: [table.dataset, table.rowId] })],
);
