import { describe, expect, it } from "vitest";
import { bucketBreaks, bucketOf } from "./buckets.ts";

describe("bucketBreaks", () => {
  it("splits counts into quantiles, ignoring zeros", () => {
    expect(bucketBreaks([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])).toEqual([
      2, 4, 6, 8, 10,
    ]);
  });

  it("drops repeated bounds when counts are lumpy", () => {
    expect(bucketBreaks([1, 1, 1, 1, 50])).toEqual([1, 50]);
    expect(bucketBreaks([])).toEqual([]);
  });
});

describe("bucketOf", () => {
  it("places a count in the first bucket whose bound holds it", () => {
    const breaks = [2, 4, 6, 8, 10];
    expect(bucketOf(1, breaks)).toBe(0);
    expect(bucketOf(4, breaks)).toBe(1);
    expect(bucketOf(10, breaks)).toBe(4);
    expect(bucketOf(99, breaks)).toBe(4);
  });
});
