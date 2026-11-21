import { type Psgc, psgcAtLevel } from "#/lib/psgc.ts";
import type { AreaResolutionOutcome } from "#/providers/beneco/area-types.ts";

export interface AreaOverlayOutage extends AreaResolutionOutcome {
  ongoing: boolean;
  resolvedRecently: boolean;
}

export interface PsgcTally {
  ongoing: number;
  resolvedRecently: number;
}

export interface CountMap extends Map<Psgc, PsgcTally> {}

export interface AreaOverlayCounts {
  province: CountMap;
  city: CountMap;
  barangay: CountMap;
}

function bump(map: CountMap, psgc: Psgc, key: keyof PsgcTally, by = 1) {
  const entry = map.get(psgc) ?? { ongoing: 0, resolvedRecently: 0 };
  entry[key] += by;
  map.set(psgc, entry);
}

export function aggregateOverlay(outages: readonly AreaOverlayOutage[]): {
  counts: AreaOverlayCounts;
  partial: AreaOverlayPartial;
} {
  const province: CountMap = new Map();
  const city: CountMap = new Map();
  const barangay: CountMap = new Map();
  const wholeProvince = new Set<Psgc>();
  const wholeCity = new Set<Psgc>();
  const wholeBarangay = new Set<Psgc>();

  for (const outage of outages) {
    const tallyKey: keyof PsgcTally | null = outage.ongoing
      ? "ongoing"
      : outage.resolvedRecently
        ? "resolvedRecently"
        : null;
    if (tallyKey === null) continue;

    for (const mun of outage.municipalities) {
      if (mun.scope.kind === "included") {
        for (const b of mun.scope.barangays) {
          const bp = psgcAtLevel(b.psgc, "barangay");
          const cp = psgcAtLevel(bp, "city");
          const pp = psgcAtLevel(bp, "province");
          if (bp) {
            bump(barangay, bp, tallyKey);
            if (b.scope.kind === "whole") wholeBarangay.add(bp);
          }
          if (cp) bump(city, cp, tallyKey);
          if (pp) bump(province, pp, tallyKey);
        }
      } else {
        const cp = psgcAtLevel(mun.psgc, "city");
        const pp = psgcAtLevel(cp, "province");
        if (cp) {
          bump(city, cp, tallyKey);
          if (mun.scope.kind === "whole") wholeCity.add(cp);
        }
        if (pp) {
          bump(province, pp, tallyKey);
          if (mun.scope.kind === "whole") wholeProvince.add(pp);
        }
      }
    }
  }

  return {
    counts: { province, city, barangay },
    partial: {
      province: minusWhole(province, wholeProvince),
      city: minusWhole(city, wholeCity),
      barangay: minusWhole(barangay, wholeBarangay),
    },
  };
}

function minusWhole(counts: CountMap, whole: Set<Psgc>): Set<Psgc> {
  const out = new Set<Psgc>();
  for (const psgc of counts.keys()) {
    if (!whole.has(psgc)) out.add(psgc);
  }
  return out;
}

export function tallyColor(tally: PsgcTally): string | null {
  if (tally.ongoing > 0) {
    return RED_SHADES[Math.min(tally.ongoing, RED_SHADES.length) - 1];
  }
  if (tally.resolvedRecently > 0) return GREEN;
  return null;
}

const GREEN = "#22c55e";

const RED_SHADES = ["#f87171", "#ef4444", "#dc2626", "#b91c1c"];

export interface AreaOverlayPartial {
  province: Set<Psgc>;
  city: Set<Psgc>;
  barangay: Set<Psgc>;
}
