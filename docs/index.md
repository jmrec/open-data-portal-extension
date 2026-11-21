---
icon: lucide/rocket
---

# Get started

!!! Important

    This tags Philippine datasets with PSGC codes so they can be joined with the rest of the [Open Data Portal](https://data.bettergov.ph). It works on any CSV, TSV, JSON, JSON Lines, GeoJSON, or Parquet file that names places or has coordinates.

## Setup

**Prerequisites**

- `git`
- `uv`
- `just`

**Steps**

1. Clone the repository:

    ```bash
    git clone https://github.com/jmrec/open-data-portal-extension.git
    ```

2. Open in the IDE of your choice.
3. Run

    ```bash
    uv sync
    just build-reference
    ```

    `just build-reference` downloads the PSGC release and builds `data/psgc-v1.0.1.duckdb`. To tag coordinates as well, first build the barangay boundaries in [ph-administrative-boundaries](https://github.com/jmrec/ph-administrative-boundaries) (`uv run cli build bgysubmuns_parquet`).

## Usage

### Tagging a file

```bash
just try data.csv -o tagged.csv
```

Each row gets `psgc_code`, `psgc_level`, `psgc_status` (`auto`, `needs_review`, or `no_place`), and `psgc_confidence`. If a column is detected wrongly, set it with `--column NAME=SETTING`, e.g. `--column Town=city_municipality`.

### Tagging the manifest

`manifest.toml` lists datasets by `name` and `source` (a local file or an https URL):

```bash
just run              # every dataset, written to data/output/<name>.csv
just run memberships  # just one
```

### Checking accuracy

```bash
just eval
```

This compares the datasets marked `eval = true` with their baselines, and scores them against the places checked by hand in `evals/labels/`. See [Architecture](architecture.md#evaluation) for how to add labels.

## Credits

Depends on https://github.com/faeldon/philippines-psgc-shapefiles and PSA's [Summary of Changes](https://psa.gov.ph/classification/psgc).

*[PSGC]: Philippine Standard Geographic Code
