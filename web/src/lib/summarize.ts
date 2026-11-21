import type { SourceRow } from "#/catalog/queries.ts";

const ID_COLUMN = /(^|[\s_-])id$/i;
const NAME_COLUMN = /name|title/i;

/**
 * A one-line summary of a source row whose columns aren't known ahead of time:
 * name-like columns first, ids and long values left out.
 */
export function summarize(row: SourceRow): { title: string; rest: string } {
  const shown = Object.entries(row).filter(
    ([key, value]) =>
      !ID_COLUMN.test(key) &&
      (typeof value === "string" || typeof value === "number") &&
      String(value).trim() !== "" &&
      String(value).length <= 80,
  );
  const named = shown.filter(([key]) => NAME_COLUMN.test(key));
  const ordered = [
    ...named,
    ...shown.filter(([key]) => !NAME_COLUMN.test(key)),
  ];
  const values = ordered.map(([, value]) => String(value));
  return { title: values[0] ?? "(row)", rest: values.slice(1, 4).join(" · ") };
}
