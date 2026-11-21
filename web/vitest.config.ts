import { defineConfig } from "vitest/config";

// Tests skip vite.config.ts and its Start, Nitro, and devtools plugins.
export default defineConfig({
  resolve: { tsconfigPaths: true },
});
