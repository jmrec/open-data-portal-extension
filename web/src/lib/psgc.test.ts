import { describe, expect, it } from "vitest";
import { psgcAtLevel, psgcLevel } from "./psgc.ts";

const KABAYANIHAN = "1430300142"; // barangay in the City of Baguio
const BAGUIO = "1430300000"; // highly urbanized city
const BENGUET = "1401100000"; // Baguio's province, not in its code
const LA_TRINIDAD = "1401110000"; // municipality of Benguet
const TONDO_BARANGAY = "1380601001"; // under the Tondo I/II sub-municipality
const MANILA = "1380600000";

describe("psgcLevel", () => {
  it("reads levels from the hierarchy, not the code's length", () => {
    expect(psgcLevel(KABAYANIHAN)).toBe("barangay");
    expect(psgcLevel(BAGUIO)).toBe("city");
    expect(psgcLevel(LA_TRINIDAD)).toBe("city");
    expect(psgcLevel(BENGUET)).toBe("province");
  });

  it("rejects regions, sub-municipalities, and OCHA pcodes", () => {
    expect(psgcLevel("1400000000")).toBeNull();
    expect(psgcLevel("1380601000")).toBeNull();
    expect(psgcLevel("PH1401102142")).toBeNull();
  });
});

describe("psgcAtLevel", () => {
  it("walks a barangay in a highly urbanized city up to its province", () => {
    expect(psgcAtLevel(KABAYANIHAN, "barangay")).toBe(KABAYANIHAN);
    expect(psgcAtLevel(KABAYANIHAN, "city")).toBe(BAGUIO);
    expect(psgcAtLevel(KABAYANIHAN, "province")).toBe(BENGUET);
    expect(psgcAtLevel(BAGUIO, "province")).toBe(BENGUET);
  });

  it("skips Manila's sub-municipalities", () => {
    expect(psgcAtLevel(TONDO_BARANGAY, "city")).toBe(MANILA);
  });

  it("never walks down or past an unknown code", () => {
    expect(psgcAtLevel(BAGUIO, "barangay")).toBeUndefined();
    expect(psgcAtLevel(BENGUET, "city")).toBeUndefined();
    expect(psgcAtLevel(undefined, "city")).toBeUndefined();
    expect(psgcAtLevel("PH1401102142", "city")).toBeUndefined();
  });
});
