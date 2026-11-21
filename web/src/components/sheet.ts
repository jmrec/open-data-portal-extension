import { type AreaLevel, psgcAtLevel } from "#/lib/psgc.ts";
import type {
  BarangayAffect,
  MunicipalityAffect,
} from "#/providers/beneco/area-types.ts";
import type { AreaOverlayOutage } from "./area-overlay.ts";

export {
  type AreaLevel,
  psgcAtLevel,
  psgcLevel as areaLevelOf,
} from "#/lib/psgc.ts";

export interface AreaLabels {
  primary: string;
  secondary?: string;
  tertiary?: string;
}

export type SheetNode =
  | { kind: "area"; psgc: string; labels: AreaLabels }
  | { kind: "outage"; outageId: number; scheduled: boolean };

export function isAreaNode(
  node: SheetNode,
): node is Extract<SheetNode, { kind: "area" }> {
  return node.kind === "area";
}

export function currentAreaNode(nodes: readonly SheetNode[]): SheetNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    if (isAreaNode(nodes[i])) return nodes[i];
  }
  return null;
}

export interface AffectedArea {
  level: AreaLevel;
  psgc?: string;
  name: string;
  context?: string;
  whole: boolean;
}

function includedBarangays(
  mun: MunicipalityAffect,
): { barangay: BarangayAffect; whole: boolean }[] {
  if (mun.scope.kind !== "included") return [];
  const out: { barangay: BarangayAffect; whole: boolean }[] = [];
  for (const barangay of mun.scope.barangays) {
    if (barangay.scope.kind === "excluded") continue;
    out.push({
      barangay,
      whole: barangay.scope.kind === "whole",
    });
  }
  return out;
}

export function affectedAreasOf(
  outage: AreaOverlayOutage,
  level: AreaLevel,
  provinceName = "Province",
): AffectedArea[] {
  const result: AffectedArea[] = [];
  const seen = new Set<string>();

  if (level === "barangay") {
    for (const mun of outage.municipalities) {
      for (const { barangay, whole } of includedBarangays(mun)) {
        const key = barangay.psgc ?? `${mun.id}:${barangay.id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        result.push({
          level: "barangay",
          psgc: barangay.psgc,
          name: barangay.name,
          context: mun.name,
          whole,
        });
      }
    }
    return result;
  }

  if (level === "city") {
    for (const mun of outage.municipalities) {
      if (mun.scope.kind === "excluded") continue;
      // Prefer the municipality's own psgc, else derive it from its barangays.
      const fromBarangays = includedBarangays(mun)[0]?.barangay.psgc;
      const psgc =
        psgcAtLevel(mun.psgc, "city") ?? psgcAtLevel(fromBarangays, "city");
      const key = psgc ?? `mun:${mun.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({
        level: "city",
        psgc,
        name: mun.name,
        whole: mun.scope.kind === "whole",
      });
    }
    return result;
  }

  // province
  const seenProv = new Set<string>();
  const anyWhole = outage.municipalities.every(
    (mun) => mun.scope.kind === "whole",
  );
  for (const mun of outage.municipalities) {
    const psgc = psgcAtLevel(mun.psgc, "province");
    if (psgc) {
      if (seenProv.has(psgc)) continue;
      seenProv.add(psgc);
      result.push({
        level: "province",
        psgc,
        name: provinceName,
        whole: anyWhole,
      });
      return result;
    }
    const first = includedBarangays(mun)[0]?.barangay.psgc;
    const derived = psgcAtLevel(first, "province");
    if (derived) {
      if (seenProv.has(derived)) continue;
      seenProv.add(derived);
      result.push({
        level: "province",
        psgc: derived,
        name: provinceName,
        whole: anyWhole,
      });
      return result;
    }
  }
  return result;
}

/**
 * The psgcs (at `level`) an outage affects — a fast membership view over
 * {@link affectedAreasOf}. Used for map highlighting.
 */
export function affectedPsgcsOf(
  outage: AreaOverlayOutage,
  level: AreaLevel,
  provinceName = "Province",
): Set<string> {
  const out = new Set<string>();
  for (const area of affectedAreasOf(outage, level, provinceName)) {
    if (area.psgc) out.add(area.psgc);
  }
  return out;
}

/** Whether an outage is currently shown/colored on the map. */
export function isActiveOverlay(outage: AreaOverlayOutage): boolean {
  return outage.ongoing || outage.resolvedRecently;
}

/**
 * The outages relevant to a given area (identified by its own-level psgc):
 * active/resolved-recent outages whose affected set at that level includes it.
 */
export function outagesAffecting(
  outages: readonly AreaOverlayOutage[],
  level: AreaLevel,
  psgc: string,
): AreaOverlayOutage[] {
  const want = psgcAtLevel(psgc, level) ?? psgc;
  const result: AreaOverlayOutage[] = [];
  for (const outage of outages) {
    if (!isActiveOverlay(outage)) continue;
    if (affectedPsgcsOf(outage, level).has(want)) result.push(outage);
  }
  return result;
}
