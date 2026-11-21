import { createEnv } from "@t3-oss/env-core";
import { z } from "zod";

export const env = createEnv({
  server: {
    SERVER_URL: z.url().optional(),
    CATALOG_PATH: z.string().default("../data/output/catalog.sqlite"),
  },

  clientPrefix: "VITE_",

  client: {
    VITE_APP_TITLE: z.string().min(1).optional(),
    /** TileJSON of PH_Adm_Boundaries.pmtiles; `just tiles` serves it here. */
    VITE_TILE_SERVER_URL: z
      .url()
      .default("http://localhost:3080/PH_Adm_Boundaries.json"),
    /** "mlt" only behind martin, which converts on the fly. */
    VITE_TILE_ENCODING: z.enum(["mvt", "mlt"]).default("mvt"),
  },

  runtimeEnv: {
    ...import.meta.env,
    ...(typeof process === "undefined" ? {} : process.env),
  },

  emptyStringAsUndefined: true,
});
