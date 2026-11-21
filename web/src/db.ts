import { existsSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { drizzle, type NodeSQLiteDatabase } from "drizzle-orm/node-sqlite";
import { env } from "./env";

let db: NodeSQLiteDatabase | undefined;

export class CatalogMissingError extends Error {
  constructor(path: string) {
    super(
      `No catalog at ${path}. Run \`just run && just export\` at the repo root.`,
    );
  }
}

/** The tagger's catalog at CATALOG_PATH, opened read-only. */
export function getDb(): NodeSQLiteDatabase {
  if (!db) {
    if (!existsSync(env.CATALOG_PATH)) {
      throw new CatalogMissingError(env.CATALOG_PATH);
    }
    db = drizzle({
      client: new DatabaseSync(env.CATALOG_PATH, { readOnly: true }),
    });
  }
  return db;
}
