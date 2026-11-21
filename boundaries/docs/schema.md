---
icon: lucide/file-json
---

The schema found in `manifest.yml` configures how the app processes your data. Each dataset is a list of steps, and each step is a plain command.

```yaml
datasets:
  country:
    # Source reads inside `data/`. A glob merges all matches first.
    source: raw/country.0.1.json

    steps:
      - run: >
          mapshaper -i {in} -clean
          -simplify visvalingam 10% keep-shapes
          -o {out} precision=0.00001

      - run: >
          tippecanoe -o {out} -f -P
          --layer=barangays -Z4 -z14
          {in}
        out: barangays.pmtiles
```

## Sources

`source` is either one path or a mapping of names to paths. A mapping lets steps read each file by name:

```yaml
source:
  barangays: raw/barangays/*.json
  roads: raw/roads.json
```

## Steps

- `run` is the command, written as you would type it in a shell. Quoting follows shell rules.
- `{out}` is replaced by this step's output path. Every step must use it.
- `{in}` is replaced by the previous step's output. On the first step it is the source, which must be the only one if the dataset has several.
- `{name}` is replaced by a source name, or by the output of an earlier step with that `id`.
- `id` names this step's output so later steps can read it. Steps can only read earlier steps and sources.
- `out` names the file. The last step must set it, and it is written to `data/processed/`. Other steps may set it too; their files stay in `.cache/build/steps/<dataset>/`.

Steps that don't depend on each other form branches. A step that reads several names merges them, as in this example:

```yaml
- id: brgy
  run: mapshaper -i {barangays} -clean -o {out}
- id: brgy_tiles
  run: tippecanoe -o {out} -f --layer=barangays {brgy}
- id: road_tiles
  run: tippecanoe -o {out} -f --layer=roads {roads}
- run: tile-join -o {out} -f {brgy_tiles} {road_tiles}
  out: country.pmtiles
```

A step reruns when one of its inputs changes, its command text changes, or its tool's version (`<tool> --version`) changes. Steps that depend on it rerun only if its output changes. Two datasets can't write the same final `out` file.
