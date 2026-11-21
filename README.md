## Tag your datasets

List your datasets in [`manifest.toml`](manifest.toml), then run them:

```bash
# optional, to tag coordinates: run
# `just build-boundaries bgysubmuns_parquet` (or set PSGC_BOUNDARIES to the .parquet)
just build-reference   # once: download PSGC and build the reference database
just run               # tag every dataset in the manifest
just run memberships   # or just one
```

A manifest entry needs a `name` and a `source`, a local file or an https URL
(CSV, TSV, JSON, JSON Lines, GeoJSON, or Parquet):

```toml
[[datasets]]
name = "health_facilities"
source = "data/health_facilities.csv"
level = "barangay"                    # optional: warn if detection finds less

[datasets.columns]                    # optional: fix what detection gets wrong
Bayan = "city_municipality"
Remarks = "ignore"
```

Coordinates are used too: `latitude`/`longitude` columns (or `lat`, `lon`,
`lng`), a GeoJSON geometry, or columns set to `"latitude"` and `"longitude"`
under `[datasets.columns]`. Each point is tagged with the barangay it falls in,
once the boundaries are built. A point just outside every barangay takes the
nearest one within 250 m and goes to review, unless a place name in the row
agrees.

Each tagged copy goes to `data/output/<name>.csv` (or `output = "..."`, in
`.csv`, `.parquet`, or `.jsonl`) with four columns added: `psgc_code`,
`psgc_level`, `psgc_status` (`auto`, `needs_review`, or `no_place`), and
`psgc_confidence`. The run reports the columns it detected, the auto-tag
rate, and the places sent to review that affect the most rows.

## View the results

`just export` rolls every tagged dataset up by place into
`data/output/catalog.sqlite`: each row counts at its barangay, city or
municipality, province, and region. The web app in `web/` reads it:

```bash
just export
just build-boundaries boundaries   # once: the map tiles
just tiles -d                      # serve them on http://localhost:3080
just web dev                       # http://localhost:3000
```

## Try a file without the manifest

```bash
uv run open-data-portal-extension resolve "Orani, Bataan"
just try data.csv
just try https://github.com/RobertRLeung/OpenHalalan/releases/download/data-latest/NLE_Winners_2004-2025.csv
just try data.csv --column Town=city_municipality -o tagged.parquet
```

`just try` takes the same column settings as the manifest, through
`--column NAME=SETTING`. Run any command with `--help` for its options.

## Check accuracy

Datasets marked `eval = true` in the manifest form the evaluation set.
`just eval` tags them and compares each with its baseline in
`evals/baselines/`, so a change to the pipeline shows up as a before/after.

Places checked by hand in `evals/labels/<name>.csv` give the precision of the
automatic tags. To check more:

```bash
just eval --sample 50              # add 50 unlabeled places to each labels file
just compare-barangay memberships  # optional: a second opinion from the barangay package
```

In each new row, correct `expected_code` if it is wrong and put your initials in
`checked`; only checked rows are scored. Run `just eval --save` to accept new
numbers as the baselines.

## Run the API

Start the local FastAPI server:

```bash
uv run fastapi dev
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. The
`POST /tag` endpoint accepts one source row and returns its PSGC tag:

```bash
curl -X POST http://127.0.0.1:8000/tag \
  -H 'content-type: application/json' \
  -d '{"dataset_key":"demo","row_id":"1","row":{"City/Municipality":"Laoag"}}'
```

Build the PSGC reference database once, then point the API at it:

```bash
just build-reference
PSGC_REFERENCE_DB=data/psgc-v1.0.1.duckdb uv run fastapi dev
```

Without `PSGC_REFERENCE_DB` the endpoint uses a four-place demo set for local
testing, and `GET /health` reports its `psgc_version`. A `PSGC_REFERENCE_DB`
that does not exist is an error.

Run the test suite with:

```bash
uv run pytest
```
