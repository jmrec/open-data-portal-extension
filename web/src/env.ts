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
    VITE_TILE_SERVER_URL: z.url().default("http://localhost:3080/boundaries"),
  },

  runtimeEnv: {
    ...import.meta.env,
    ...(typeof process === "undefined" ? {} : process.env),
  },

  emptyStringAsUndefined: true,
});
