import { config } from "dotenv";
import { defineConfig } from "drizzle-kit";

config({ path: [".env.local", ".env"], override: true });

export default defineConfig({
  out: "./drizzle",
  schema: [
    "./src/outages/repository-schema.ts",
    "./src/providers/beneco/area-schema.ts",
  ],
  dialect: "sqlite",
  dbCredentials: {
    url: process.env.DATABASE_PATH ?? "data/beacon.sqlite",
  },
});
