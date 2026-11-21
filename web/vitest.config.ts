import { defineConfig } from "vitest/config";

// Tests skip vite.config.ts: its Neon plugin provisions a database whenever
// .env has no DATABASE_URL.
export default defineConfig({
  resolve: { tsconfigPaths: true },
});
