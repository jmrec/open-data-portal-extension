import hierarchy from "#/data/psgc-hierarchy.json";

export type Psgc = string;
export type AreaLevel = "barangay" | "city" | "province";

const provinceOfCity: Record<Psgc, Psgc> = hierarchy.provinceOfCity;
const cityOfSubMunicipality: Record<Psgc, Psgc> =
  hierarchy.cityOfSubMunicipality;
const provinces = new Set(Object.values(provinceOfCity));

const PSGC_PATTERN = /^\d{10}$/;

/** The level of a code, or null for regions, sub-municipalities, and non-PSGC strings. */
export function psgcLevel(code: Psgc): AreaLevel | null {
  if (!PSGC_PATTERN.test(code)) return null;
  if (code in provinceOfCity) return "city";
  if (provinces.has(code)) return "province";
  if (code in cityOfSubMunicipality) return null;
  return code.endsWith("000") ? null : "barangay";
}

/**
 * The code itself, or its ancestor, at `level`. Undefined when the code is
 * missing, unknown, or below `level` asks for a descendant.
 */
export function psgcAtLevel(
  code: Psgc | undefined,
  level: AreaLevel,
): Psgc | undefined {
  if (!code) return undefined;
  const own = psgcLevel(code);
  if (own === null) return undefined;
  if (own === level) return code;
  if (own === "province") return undefined;
  const city =
    own === "city"
      ? code
      : (cityOfSubMunicipality[`${code.slice(0, 7)}000`] ??
        `${code.slice(0, 7)}000`);
  if (level === "city") return city in provinceOfCity ? city : undefined;
  if (level === "province") return provinceOfCity[city];
  return undefined;
}
