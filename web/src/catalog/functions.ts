import { createServerFn } from "@tanstack/react-start";
import { getDb } from "../db.ts";
import { type AdminLevel, LEVEL_IDS } from "./levels.ts";
import { listDatasets, placeCounts_, placeDetail } from "./queries.ts";

function isLevel(value: unknown): value is AdminLevel {
  return LEVEL_IDS.includes(value as AdminLevel);
}

export const getPlaceCounts = createServerFn({ method: "GET" })
  .validator((data: { level: AdminLevel; dataset?: string }) => {
    if (!isLevel(data.level)) throw new Error(`unknown level: ${data.level}`);
    return data;
  })
  .handler(({ data }) => placeCounts_(getDb(), data.level, data.dataset));

export const getPlace = createServerFn({ method: "GET" })
  .validator((data: { code: string }) => {
    if (!/^\d{10}$/.test(data.code)) throw new Error("not a PSGC code");
    return data;
  })
  .handler(({ data }) => placeDetail(getDb(), data.code));

export const getDatasets = createServerFn({ method: "GET" }).handler(() =>
  listDatasets(getDb()),
);
