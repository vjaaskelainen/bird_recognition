import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { listVideos } from "@/api/videos";
import { BulkConfirm } from "@/components/BulkConfirm";
import { ErrorBanner } from "@/components/Shell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  PAGE_SIZE,
  isDefaultTriage,
  parseFilters,
  serializeFilters,
  type Filters,
  type SortKey,
} from "@/lib/filters";

const STATUS_OPTIONS = ["no_animals", "animals", "failed", "not_ingested"] as const;

export function Videos() {
  const [params, setParams] = useSearchParams();
  const filters = parseFilters(params);
  const update = (patch: Partial<Filters>) =>
    setParams(serializeFilters({ ...filters, page: 1, ...patch }));

  const query = useQuery({
    queryKey: ["videos", params.toString()],
    queryFn: () => listVideos(filters),
  });
  const error = query.error;
  const manifestMissing = error instanceof ApiError && error.code === "manifest_unavailable";
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const bulkIds = items.flatMap((item) => (item.source_id ? [item.source_id] : []));

  return (
    <div>
      <h1 className="mb-3 text-lg font-semibold">Videos</h1>
      <form
        className="mb-3 flex flex-wrap items-end gap-3 text-sm"
        onSubmit={(e) => e.preventDefault()}
      >
        <fieldset className="flex gap-2">
          <legend className="sr-only">Status</legend>
          {STATUS_OPTIONS.map((value) => (
            <label key={value} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={filters.status.includes(value)}
                onChange={(event) =>
                  update({
                    status: event.target.checked
                      ? [...filters.status, value]
                      : filters.status.filter((item) => item !== value),
                  })
                }
              />
              {value.replace("_", " ")}
            </label>
          ))}
        </fieldset>
        <label className="flex flex-col">
          Review
          <select
            value={filters.review ?? ""}
            onChange={(event) =>
              update({ review: (event.target.value || null) as Filters["review"] })
            }
            className="rounded border border-line px-2 py-1"
          >
            <option value="">any</option>
            <option value="unreviewed">unreviewed</option>
            <option value="confirmed">confirmed</option>
            <option value="corrected">corrected</option>
          </select>
        </label>
        <label className="flex flex-col">
          Folder
          <input
            defaultValue={filters.folder}
            onBlur={(event) => update({ folder: event.target.value })}
            className="rounded border border-line px-2 py-1"
          />
        </label>
        <label className="flex flex-col">
          From
          <input
            type="date"
            value={filters.from}
            onChange={(e) => update({ from: e.target.value })}
            className="rounded border border-line px-2 py-1"
          />
        </label>
        <label className="flex flex-col">
          To
          <input
            type="date"
            value={filters.to}
            onChange={(e) => update({ to: e.target.value })}
            className="rounded border border-line px-2 py-1"
          />
        </label>
        <label className="flex flex-col">
          Sort
          <select
            value={filters.sort}
            onChange={(event) => update({ sort: event.target.value as SortKey })}
            className="rounded border border-line px-2 py-1"
          >
            <option value="capture_start">capture time</option>
            <option value="basename">name</option>
            <option value="ingested_at">ingested</option>
            <option value="crop_count">crops</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => update({ order: filters.order === "asc" ? "desc" : "asc" })}
          className="rounded border border-line px-2 py-1"
        >
          {filters.order === "asc" ? "Ascending" : "Descending"}
        </button>
      </form>

      {manifestMissing ? (
        <div role="alert" className="rounded border border-line bg-surface p-4 text-sm">
          The video manifest is not configured. Set <code>BIRD_RECOGNITION_API_MANIFEST</code> to a
          manifest file (see docs/usage.md) and restart the service.
        </div>
      ) : (
        <ErrorBanner error={error} onRetry={() => void query.refetch()} />
      )}

      {isDefaultTriage(filters) && bulkIds.length > 0 && (
        <BulkConfirm sourceIds={bulkIds} total={bulkIds.length} />
      )}

      {query.isSuccess && items.length === 0 && (
        <p className="rounded border border-line bg-surface p-4 text-sm text-ink-muted">
          No videos match these filters.
        </p>
      )}

      <ul className="divide-y divide-line rounded border border-line bg-surface">
        {items.map((video) => (
          <li
            key={video.path_id}
            data-testid="video-row"
            className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm"
          >
            {video.source_id ? (
              <Link
                to={`/review?video=${encodeURIComponent(video.source_id)}`}
                className="font-medium text-accent"
              >
                {video.basename}
              </Link>
            ) : (
              <span className="font-medium">{video.basename}</span>
            )}
            <span className="text-ink-muted">{video.folder}</span>
            <span className="text-ink-muted">{video.capture_start ?? "unknown time"}</span>
            <StatusBadge video={video} />
            <span className="ml-auto text-ink-muted">
              {video.crop_count} crops{video.top_label ? ` · ${video.top_label}` : ""}
            </span>
          </li>
        ))}
      </ul>

      <nav className="mt-3 flex items-center gap-3 text-sm" aria-label="Pagination">
        <button
          type="button"
          disabled={filters.page <= 1}
          onClick={() => update({ page: filters.page - 1 })}
          className="rounded border border-line px-2 py-1 disabled:opacity-50"
        >
          Previous
        </button>
        <span>
          Page {filters.page} of {pages} · {total} videos
        </span>
        <button
          type="button"
          disabled={filters.page >= pages}
          onClick={() => update({ page: filters.page + 1 })}
          className="rounded border border-line px-2 py-1 disabled:opacity-50"
        >
          Next
        </button>
      </nav>
    </div>
  );
}
