---
icon: lucide/rocket
---

# Get started

!!! Important

    This is primarily for processing administrative boundaries in the Philippines as a utility project for [Open Data Portal Extension](https://datax-docs.jmrecondo.com). However, it supports any other workflow provided you have the command installed and executable via the CLI.
    

    The Dev Container makes the `mapshaper`, `tippecanoe`, and `mlt` commands available in the CLI.

## Setup

=== "Dev Container (Recommended)"

    **Prerequisites**

    - Docker

    **Steps**

    1. Open in the IDE of your choice and reopen in container. 
    2. Run

        ```bash
        uv sync
        ```

=== "Manual"

    **Prerequisites**

    - `git`
    - Commands installed in your PC: `mapshaper`, `tippecanoe`, `mlt`
    - `uv`

    **Steps**

    1. Clone the repository:

        ```bash
        git clone https://github.com/jmrec/ph-administrative-boundaries.git
        ```

    2. Open in the IDE of your choice.
    3. Run

        ```bash
        uv sync
        ```

## Usage

### Building with the CLI

[manifest.yml](/schema) declares each dataset's source and its ordered steps:

```bash
uv run cli build <dataset>
```

Finished tiles are written to `data/processed/` (override with `--output-dir`). Each step's output is cached, so rebuilding only reruns steps whose input, command, or tool version changed.

A dataset's `source` resolves under the manifest's `data/` directory and may be a single file or a glob (e.g. `raw/municities/*.json`), or a mapping of names to such paths. Glob matches are merged into one FeatureCollection (written to `.cache/build/raw/<dataset>/`), which is what steps read. That merged copy is deleted after each run unless you pass `--keep-intermediates`.

<!-- ## Good defaults I found

| Command | Use case | Defaults |
| --- | --- | --- |
| `mapshaper` | | |
| `tippecanoe` | | |
| `mlt` | | | -->

## Credits

Depends on https://github.com/faeldon/philippines-psgc-shapefiles.

*[CLI]: Command Line Interface