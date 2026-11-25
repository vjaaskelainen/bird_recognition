export type Status = "not_ingested" | "no_animals" | "animals" | "failed";
export type ReviewFilter = "unreviewed" | "confirmed" | "corrected";
export type SortKey = "capture_start" | "basename" | "ingested_at" | "crop_count";

export interface Filters {
  status: Status[];
  review: ReviewFilter | null;
  folder: string;
  from: string;
  to: string;
  sort: SortKey;
  order: "asc" | "desc";
  page: number;
}

export const PAGE_SIZE = 50;
const STATUSES: Status[] = ["not_ingested", "no_animals", "animals", "failed"];
const REVIEWS: ReviewFilter[] = ["unreviewed", "confirmed", "corrected"];
const SORTS: SortKey[] = ["capture_start", "basename", "ingested_at", "crop_count"];

export function defaultFilters(): Filters {
  return {
    status: ["no_animals"],
    review: "unreviewed",
    folder: "",
    from: "",
    to: "",
    sort: "capture_start",
    order: "asc",
    page: 1,
  };
}

/** Parse URL params; an explicitly empty status/review means "any". */
export function parseFilters(params: URLSearchParams): Filters {
  const base = defaultFilters();
  const status = params.has("status")
    ? params
        .getAll("status")
        .flatMap((value) => value.split(","))
        .filter((value): value is Status => STATUSES.includes(value as Status))
    : base.status;
  const reviewParam = params.get("review");
  const review = params.has("review")
    ? REVIEWS.includes(reviewParam as ReviewFilter)
      ? (reviewParam as ReviewFilter)
      : null
    : base.review;
  const sort = params.get("sort") as SortKey | null;
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  return {
    status,
    review,
    folder: params.get("folder") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    sort: sort && SORTS.includes(sort) ? sort : base.sort,
    order: params.get("order") === "desc" ? "desc" : "asc",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** Serialize every non-default value so a copied URL reproduces the view. */
export function serializeFilters(filters: Filters): URLSearchParams {
  const base = defaultFilters();
  const params = new URLSearchParams();
  if (filters.status.join() !== base.status.join()) {
    if (filters.status.length === 0) params.set("status", "");
    for (const value of filters.status) params.append("status", value);
  }
  if (filters.review !== base.review) params.set("review", filters.review ?? "");
  if (filters.folder) params.set("folder", filters.folder);
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.sort !== base.sort) params.set("sort", filters.sort);
  if (filters.order !== base.order) params.set("order", filters.order);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params;
}

export function isDefaultTriage(filters: Filters): boolean {
  return (
    filters.status.join() === "no_animals" &&
    filters.review === "unreviewed" &&
    !filters.folder &&
    !filters.from &&
    !filters.to
  );
}
