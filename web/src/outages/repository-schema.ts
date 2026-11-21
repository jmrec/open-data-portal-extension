import {
  index,
  integer,
  primaryKey,
  sqliteTable,
  text,
} from "drizzle-orm/sqlite-core";
import type {
  AreaResolution,
  AreaTask,
} from "../providers/beneco/area-types.ts";

export const resolvedOutages = sqliteTable(
  "resolved_outages",
  {
    companyId: text("company_id").notNull().default("beneco"),
    outageId: integer("outage_id").notNull(),
    kind: text("kind").$type<AreaTask["kind"]>().notNull(),
    key: text("key").notNull(),
    fingerprint: text("fingerprint").notNull(),
    resolution: text("resolution", { mode: "json" })
      .$type<AreaResolution>()
      .notNull(),
    resolvedAt: integer("resolved_at", { mode: "timestamp_ms" })
      .notNull()
      .$defaultFn(() => new Date()),
  },
  (table) => [
    primaryKey({ columns: [table.companyId, table.outageId] }),
    index("resolved_outages_resolved_at_idx").on(table.resolvedAt),
  ],
);
