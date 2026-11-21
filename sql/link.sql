-- Link openhalalan_winners.csv and critical_facilities.csv through the PSGC hierarchy.
--
-- Facilities are tagged at barangay level; winners at city/municipality or province
-- level, depending on the office. Both are joined on the PSGC lineage from the
-- reference database, so a barangay facility links to its municipality's mayor and
-- councilors and to its province's governor, board members and House members.
--
-- Run from the repo root (`just link`). Rebuild whenever either CSV is re-tagged.
-- Base tables are materialized so the views work without the reference DB attached.

ATTACH 'data/psgc-v1.0.1.duckdb' AS ref (READ_ONLY);

-- Every PSGC entry with its ancestor at each level (itself included).
CREATE OR REPLACE TABLE psgc_lineage AS
WITH RECURSIVE chain(code, ancestor_code) AS (
    SELECT code, code FROM ref.psgc_entries
    UNION ALL
    SELECT chain.code, e.parent_code
    FROM chain
    JOIN ref.psgc_entries e ON e.code = chain.ancestor_code
    WHERE e.parent_code IS NOT NULL
)
SELECT
    chain.code,
    max(a.code) FILTER (a.level = 'barangay')          AS barangay_code,
    max(a.name) FILTER (a.level = 'barangay')          AS barangay_name,
    max(a.code) FILTER (a.level = 'city_municipality') AS city_municipality_code,
    max(a.name) FILTER (a.level = 'city_municipality') AS city_municipality_name,
    max(a.code) FILTER (a.level = 'province')          AS province_code,
    max(a.name) FILTER (a.level = 'province')          AS province_name,
    max(a.code) FILTER (a.level = 'region')            AS region_code,
    max(a.name) FILTER (a.level = 'region')            AS region_name
FROM chain
JOIN ref.psgc_entries a ON a.code = chain.ancestor_code
GROUP BY chain.code;

CREATE OR REPLACE TABLE facilities AS
SELECT row_number() OVER () AS facility_id, *
FROM read_csv('data/output/critical_facilities.csv', all_varchar = true);

CREATE OR REPLACE TABLE winners AS
SELECT row_number() OVER () AS winner_id, *
FROM read_csv('data/output/openhalalan_winners.csv', all_varchar = true);

DETACH ref;

-- Facilities with their full place lineage (untagged facilities keep NULL codes).
CREATE OR REPLACE VIEW facility_places AS
SELECT f.*, l.* EXCLUDE (code)
FROM facilities f
LEFT JOIN psgc_lineage l ON l.code = f.psgc_code;

-- Winners with the code of the LGU their office governs. National offices
-- (senator, president, vice president) have no jurisdiction code.
CREATE OR REPLACE VIEW winner_places AS
SELECT
    w.*,
    w.psgc_code  AS jurisdiction_code,
    w.psgc_level AS jurisdiction_level,
    l.city_municipality_name,
    l.province_code,
    l.province_name,
    l.region_code,
    l.region_name
FROM winners w
LEFT JOIN psgc_lineage l ON l.code = w.psgc_code;

-- Many-to-many: each facility × every official (all election years) whose
-- jurisdiction contains it. Filter on "Year" before materializing this.
CREATE OR REPLACE VIEW facility_officials AS
SELECT
    f.facility_id, f.type, f.name AS facility_name, f.amenity, f.osm_id, f.geometry,
    f.barangay_code, f.barangay_name,
    f.city_municipality_code, f.city_municipality_name,
    f.province_code, f.province_name,
    w.winner_id, w."Full Name", w."Position", w."Party", w."Year", w."Sex",
    w.jurisdiction_code, w.jurisdiction_level
FROM facility_places f
JOIN winner_places w
  ON (w.jurisdiction_level = 'city_municipality' AND w.jurisdiction_code = f.city_municipality_code)
  OR (w.jurisdiction_level = 'province'          AND w.jurisdiction_code = f.province_code);

-- Facility counts per city/municipality and per province.
CREATE OR REPLACE VIEW lgu_facility_counts AS
WITH per_level AS (
    SELECT 'city_municipality' AS level, city_municipality_code AS code, type FROM facility_places
    UNION ALL
    SELECT 'province', province_code, type FROM facility_places
)
SELECT
    level, code,
    count(*)                                  AS facilities,
    count(*) FILTER (type = 'hospital')       AS hospitals,
    count(*) FILTER (type = 'school')         AS schools,
    count(*) FILTER (type = 'police_station') AS police_stations,
    count(*) FILTER (type = 'fire_station')   AS fire_stations
FROM per_level
WHERE code IS NOT NULL
GROUP BY ALL;

-- One row per winner with the facility counts of the LGU they govern
-- (zeros for an LGU with no tagged facilities; NULL for national offices).
CREATE OR REPLACE VIEW winner_facility_counts AS
SELECT
    w.*,
    CASE WHEN w.jurisdiction_code IS NOT NULL THEN coalesce(c.facilities, 0)      END AS facilities,
    CASE WHEN w.jurisdiction_code IS NOT NULL THEN coalesce(c.hospitals, 0)       END AS hospitals,
    CASE WHEN w.jurisdiction_code IS NOT NULL THEN coalesce(c.schools, 0)         END AS schools,
    CASE WHEN w.jurisdiction_code IS NOT NULL THEN coalesce(c.police_stations, 0) END AS police_stations,
    CASE WHEN w.jurisdiction_code IS NOT NULL THEN coalesce(c.fire_stations, 0)   END AS fire_stations
FROM winner_places w
LEFT JOIN lgu_facility_counts c
  ON c.level = w.jurisdiction_level AND c.code = w.jurisdiction_code;
