import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { drizzle, type NodeSQLiteDatabase } from "drizzle-orm/node-sqlite";
import { migrate } from "drizzle-orm/node-sqlite/migrator";
import { env } from "./env";

let db: NodeSQLiteDatabase | undefined;

/**
 * The app's SQLite database at DATABASE_PATH. Opening it applies any pending
 * migrations, which also seed BENECO's service area, so a fresh checkout works
 * with no setup.
 */
export function getDb(): NodeSQLiteDatabase {
  if (!db) {
    mkdirSync(dirname(env.DATABASE_PATH), { recursive: true });
    db = drizzle(env.DATABASE_PATH);
    migrate(db, { migrationsFolder: env.DATABASE_MIGRATIONS });
  }
  return db;
}
