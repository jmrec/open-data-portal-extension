import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { devtools } from "@tanstack/devtools-vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact, { reactCompilerPreset } from "@vitejs/plugin-react";
import { nitro } from "nitro/vite";
import { defineConfig } from "vite";

const config = defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  optimizeDeps: {
    exclude: ["maplibre-gl"],
  },
  plugins: [
    devtools({
      injectSource: {
        enabled: true,
        ignore: { components: [/AgGrid/i] },
      },
    }),
    nitro({
      rollupConfig: {
        external: [/^@sentry\//],
      },
    }),
    tailwindcss(),
    tanstackStart(),
    viteReact(),
    babel({
      presets: [reactCompilerPreset()],
    }),
  ],
  server: {
    host: true,
  },
});
export default config;
