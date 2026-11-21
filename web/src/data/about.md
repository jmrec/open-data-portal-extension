Philippine open data is published by many agencies, and each writes place names its own way: "Sto. Niño" or "Santo Niño", a town that has since become a city, one of hundreds of barangays named Poblacion. While datasets carry only free-text names, each one stands alone.

Beacon shows what changes once every row carries a **PSGC code**, the Philippine Standard Geographic Code the PSA assigns to each region, province, city, municipality and barangay. Pick a place on the map and you see every dataset with rows there, side by side.

## How it works

1. **Tag.** The tagger in this repository reads each dataset in its manifest, finds the place columns, and matches them to PSGC codes, including old names and boundaries. A match it isn't sure of goes to review instead of being guessed.
2. **Roll up.** `just export` counts each tagged row at its barangay, city or municipality, province and region. A highly urbanized city counts in the province it sits in (the City of Baguio in Benguet) even though its code doesn't contain the province's.
3. **Show.** This site reads that catalog. The boundaries come from the PSGC shapefiles, built into vector tiles in `boundaries/`.

Counts include only rows the tagger placed automatically. Rows sent to review aren't on the map until someone checks them.
