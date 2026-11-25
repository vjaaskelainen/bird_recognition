import { describe, expect, it } from "vitest";
import { defaultFilters, parseFilters, serializeFilters } from "@/lib/filters";

describe("filters", () => {
  it("defaults to unreviewed no-animal videos", () => {
    const filters = parseFilters(new URLSearchParams());
    expect(filters.status).toEqual(["no_animals"]);
    expect(filters.review).toBe("unreviewed");
    expect(serializeFilters(filters).toString()).toBe("");
  });

  it("round-trips every parameter", () => {
    const url =
      "status=animals&status=failed&review=corrected&folder=a%2Fb&from=2026-01-01&to=2026-02-01&sort=basename&order=desc&page=3";
    const filters = parseFilters(new URLSearchParams(url));
    expect(filters).toEqual({
      status: ["animals", "failed"],
      review: "corrected",
      folder: "a/b",
      from: "2026-01-01",
      to: "2026-02-01",
      sort: "basename",
      order: "desc",
      page: 3,
    });
    expect(parseFilters(serializeFilters(filters))).toEqual(filters);
  });

  it("keeps explicit 'any' selections distinct from defaults", () => {
    const filters = { ...defaultFilters(), status: [], review: null };
    const round = parseFilters(serializeFilters(filters));
    expect(round.status).toEqual([]);
    expect(round.review).toBeNull();
  });

  it("ignores invalid values", () => {
    const filters = parseFilters(new URLSearchParams("status=bogus&sort=x&page=-2"));
    expect(filters.status).toEqual([]);
    expect(filters.sort).toBe("capture_start");
    expect(filters.page).toBe(1);
  });
});
