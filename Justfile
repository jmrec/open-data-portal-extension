# Alias to `just -l`
default:
    just -l

# Run library skills
library-skills *flags:
    uvx library-skills {{ flags }}

# Show project file structure
tree:
    tree --dirsfirst -I ".agents|.cache|.venv|site|__pycache__" .

boundaries := env("PSGC_BOUNDARIES", "boundaries/data/processed/PH_Adm4_BgySubMuns.parquet")

# Download one release's PSGC CSVs and build the reference database.
build-reference tag="v1.0.1" released_on="2026-10-12":
    mkdir -p data/psgc/{{ tag }}
    for f in PH_Adm1_Regions PH_Adm2_ProvDists PH_Adm3_MuniCities PH_Adm4_BgySubMuns; do \
        curl -fsSL -o data/psgc/{{ tag }}/$f.csv \
            https://github.com/faeldon/philippines-psgc-shapefiles/releases/download/{{ tag }}/$f.csv; \
    done
    changes=$(ls data/psa/*.xlsx 2>/dev/null | tail -1); \
    boundaries="{{ boundaries }}"; [ -f "$boundaries" ] || boundaries=""; \
    uv run open-data-portal-extension build-reference \
        data/psgc/{{ tag }} data/psgc-{{ tag }}.duckdb \
        --version {{ tag }} --released-on {{ released_on }} \
        ${changes:+--changes "$changes"} \
        ${boundaries:+--boundaries "$boundaries"}

# Tag the datasets in manifest.toml, e.g. `just run` or `just run memberships`.
run *args:
    uv run open-data-portal-extension run {{ args }}

# Roll the tagged datasets up by place into the viewer's catalog, after `just run`.
export *args:
    uv run open-data-portal-extension export {{ args }}

# Check the manifest's eval datasets against their baselines, e.g. `just eval --failures 10`.
eval *args:
    uv run open-data-portal-extension eval {{ args }}

# Tag any dataset (file or https URL) and report, e.g. `just try data.csv --column Town=city_municipality`.
try dataset *flags:
    uv run open-data-portal-extension tag "{{ dataset }}" {{ flags }}

# Add the barangay package's answer to a labels file, e.g. `just compare-barangay memberships`.
compare-barangay name:
    uv run --no-project --python 3.13 --with barangay==2026.10.12.0 \
        python evals/compare_barangay.py evals/labels/{{ name }}.csv

# Run the integration tests against the real reference database.
test-integration *flags:
    uv run pytest -m integration {{ flags }}

# Build a boundaries dataset, e.g. `just build-boundaries boundaries` or `just build-boundaries bgysubmuns_parquet`.
build-boundaries name *flags:
    cd boundaries && uv run --package ph-administrative-boundaries cli build {{ name }} {{ flags }}

# Serve the built boundary tiles on http://localhost:3080, with the pmtiles CLI.
tiles *flags:
    pmtiles serve boundaries/data/processed --port 3080 --cors="*" --public-url http://localhost:3080 {{ flags }}

# Serve them with martin in Docker instead; set VITE_TILE_ENCODING=mlt and
# VITE_TILE_SERVER_URL=http://localhost:3080/boundaries in web/.env.
tiles-martin *flags:
    docker compose -f boundaries/martin/compose.yml up {{ flags }}

# Run a pnpm script in the web app, e.g. `just web dev` or `just web check`.
web *args:
    pnpm -C web {{ args }}

# Browse the exported catalog in Datasette on http://localhost:8001, after `just export`.
browse *flags:
    uvx --from datasette==0.65.1 --with "setuptools<81" datasette --immutable data/output/catalog.sqlite {{ flags }}

# Run the tagger, boundaries, and web tests.
test:
    uv run pytest
    cd boundaries && uv run --package ph-administrative-boundaries pytest
    pnpm -C web check
    pnpm -C web exec vitest run
