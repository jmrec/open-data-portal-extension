import { DatabaseSync } from "node:sqlite";
import { drizzle } from "drizzle-orm/node-sqlite";
import { beforeAll, describe, expect, it } from "vitest";
import { listDatasets, placeCounts_, placeDetail } from "./queries.ts";

// A small catalog in the shape `just export` writes
// (src/open_data_portal_extension/catalog.py).
const CAR = "1400000000";
const BENGUET = "1401100000";
const LA_TRINIDAD = "1401110000";
const BETAG = "1401110002";
const BAGUIO = "1430300000"; // highly urbanized, in Benguet
const KABAYANIHAN = "1430300142";

function fixture() {
  const client = new DatabaseSync(":memory:");
  client.exec(`
    CREATE TABLE datasets (name TEXT PRIMARY KEY, description TEXT, attribution TEXT,
      license TEXT, url TEXT, rows INTEGER, auto INTEGER, needs_review INTEGER,
      no_place INTEGER);
    CREATE TABLE places (code TEXT PRIMARY KEY, name TEXT, level TEXT, parent_code TEXT);
    CREATE TABLE lineage (code TEXT PRIMARY KEY, barangay TEXT, city_municipality TEXT,
      province TEXT, region TEXT);
    CREATE TABLE place_counts (dataset TEXT, code TEXT, level TEXT, rows INTEGER,
      PRIMARY KEY (dataset, code));
    CREATE TABLE rows (dataset TEXT, row_id INTEGER, code TEXT, confidence REAL,
      data TEXT, PRIMARY KEY (dataset, row_id));

    INSERT INTO datasets VALUES
      ('facilities', 'Hospitals', 'UP WebGIS', 'ODbL', NULL, 3, 2, 1, 0),
      ('officials', NULL, NULL, NULL, NULL, 1, 1, 0, 0);
    INSERT INTO places VALUES
      ('${CAR}', 'Cordillera Administrative Region', 'region', NULL),
      ('${BENGUET}', 'Benguet', 'province', '${CAR}'),
      ('${LA_TRINIDAD}', 'La Trinidad', 'city_municipality', '${BENGUET}'),
      ('${BETAG}', 'Betag', 'barangay', '${LA_TRINIDAD}'),
      ('${BAGUIO}', 'City of Baguio', 'city_municipality', '${BENGUET}'),
      ('${KABAYANIHAN}', 'Kabayanihan', 'barangay', '${BAGUIO}');
    INSERT INTO lineage VALUES
      ('${CAR}', NULL, NULL, NULL, '${CAR}'),
      ('${BENGUET}', NULL, NULL, '${BENGUET}', '${CAR}'),
      ('${LA_TRINIDAD}', NULL, '${LA_TRINIDAD}', '${BENGUET}', '${CAR}'),
      ('${BETAG}', '${BETAG}', '${LA_TRINIDAD}', '${BENGUET}', '${CAR}'),
      ('${BAGUIO}', NULL, '${BAGUIO}', '${BENGUET}', '${CAR}'),
      ('${KABAYANIHAN}', '${KABAYANIHAN}', '${BAGUIO}', '${BENGUET}', '${CAR}');
    INSERT INTO place_counts VALUES
      ('facilities', '${KABAYANIHAN}', 'barangay', 1),
      ('facilities', '${BETAG}', 'barangay', 1),
      ('facilities', '${BAGUIO}', 'city_municipality', 1),
      ('facilities', '${LA_TRINIDAD}', 'city_municipality', 1),
      ('facilities', '${BENGUET}', 'province', 2),
      ('facilities', '${CAR}', 'region', 2),
      ('officials', '${BAGUIO}', 'city_municipality', 1),
      ('officials', '${BENGUET}', 'province', 1),
      ('officials', '${CAR}', 'region', 1);
    INSERT INTO rows VALUES
      ('facilities', 0, '${KABAYANIHAN}', 1.0, '{"name":"Notre Dame Hospital"}'),
      ('facilities', 1, '${BETAG}', 0.9, '{"name":"Benguet State University"}'),
      ('officials', 0, '${BAGUIO}', 1.0, '{"official":"A. Mayor"}');
  `);
  return drizzle({ client });
}

let db: ReturnType<typeof fixture>;
beforeAll(() => {
  db = fixture();
});

describe("placeCounts_", () => {
  it("sums datasets per place at a level, or keeps one", async () => {
    const all = new Map(await placeCounts_(db, "province"));
    expect(all.get(BENGUET)).toBe(3);
    const one = new Map(await placeCounts_(db, "city", "officials"));
    expect([...one]).toEqual([[BAGUIO, 1]]);
  });
});

describe("placeDetail", () => {
  it("names a barangay's ancestors through lineage, not its code", async () => {
    const place = await placeDetail(db, KABAYANIHAN);
    expect(place?.level).toBe("barangay");
    expect(place?.ancestors.map((a) => a.name)).toEqual([
      "Cordillera Administrative Region",
      "Benguet",
      "City of Baguio",
    ]);
    expect(place?.datasets.map((d) => [d.dataset.name, d.rows])).toEqual([
      ["facilities", 1],
    ]);
    expect(place?.datasets[0]?.sample).toEqual([
      { name: "Notre Dame Hospital" },
    ]);
  });

  it("samples rows from everywhere inside a province, busiest first", async () => {
    const place = await placeDetail(db, BENGUET);
    expect(place?.datasets.map((d) => d.dataset.name)).toEqual([
      "facilities",
      "officials",
    ]);
    expect(place?.datasets[0]?.sample).toHaveLength(2);
    expect(place?.children.map((c) => [c.name, c.rows])).toEqual([
      ["City of Baguio", 2],
      ["La Trinidad", 1],
    ]);
  });

  it("returns null for a code that isn't a place", async () => {
    expect(await placeDetail(db, "9999999999")).toBeNull();
  });

  it("lists datasets with their metadata", async () => {
    const [first] = await listDatasets(db);
    expect(first).toMatchObject({ name: "facilities", needsReview: 1 });
  });
});
