import { describe, expect, it } from "vitest";
import { summarize } from "./summarize.ts";

describe("summarize", () => {
  it("leads with a name and skips id columns", () => {
    expect(
      summarize({
        id: "01K7QAQ5SFV0EK42XQNM0KT3Q7_m2",
        person_id: "01K7QAQ5SFV0EK42XQNM0KT3Q7",
        party: "UNA",
        name: "Juan dela Cruz",
      }),
    ).toEqual({ title: "Juan dela Cruz", rest: "UNA" });
  });

  it("drops long and empty values", () => {
    const geometry = JSON.stringify({
      type: "Point",
      coordinates: [1, 2],
    }).repeat(4);
    expect(summarize({ kind: "school", geometry, note: " " })).toEqual({
      title: "school",
      rest: "",
    });
  });

  it("falls back when nothing is shown", () => {
    expect(summarize({ id: "x" }).title).toBe("(row)");
  });
});
