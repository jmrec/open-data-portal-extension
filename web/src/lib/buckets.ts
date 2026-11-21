/** Upper bounds of each bucket, from the counts at the active level. */
export function bucketBreaks(values: number[], buckets = 5): number[] {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  const breaks: number[] = [];
  for (let i = 1; i <= buckets; i++) {
    const at =
      sorted[
        Math.min(
          sorted.length - 1,
          Math.ceil((i / buckets) * sorted.length) - 1,
        )
      ];
    if (at !== undefined && at !== breaks.at(-1)) breaks.push(at);
  }
  return breaks;
}

export function bucketOf(value: number, breaks: number[]): number {
  const i = breaks.findIndex((b) => value <= b);
  return i === -1 ? breaks.length - 1 : i;
}
