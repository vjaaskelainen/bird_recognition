import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { ErrorBanner } from "@/components/Shell";

interface Hit {
  crop_id?: string;
  source_id?: string;
  elapsed_seconds?: number;
  similarity?: number;
  score?: number;
  [key: string]: unknown;
}

async function runSearch(query: string, runId: string) {
  const body = await api
    .POST("/v1/search", { body: { query, run_id: runId, limit: 20 } })
    .then(unwrap);
  return body.results as Hit[];
}

async function latestRunId(): Promise<string | null> {
  const page = await api.GET("/v1/runs", { params: { query: { limit: 1 } } }).then(unwrap);
  const first = (page as { items?: { run_id?: string }[] }).items?.[0];
  return first?.run_id ?? null;
}

export function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const run = params.get("run");
  const [text, setText] = useState(q);

  const latest = useQuery({
    queryKey: ["latest-run"],
    queryFn: latestRunId,
    enabled: !run,
    retry: false,
  });
  const runId = run ?? latest.data ?? null;
  const results = useQuery({
    queryKey: ["search", q, runId],
    queryFn: () => runSearch(q, runId as string),
    enabled: q.length > 0 && runId !== null,
    retry: false,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams(params);
    next.set("q", text.trim());
    setParams(next);
  }

  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold">Search crops</h1>
      <p className="mb-3 rounded bg-surface-muted p-2 text-xs text-ink-muted">
        Not a probability: similarity scores only rank matches.
      </p>
      <form onSubmit={submit} className="mb-3 flex gap-2">
        <input
          aria-label="Query"
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="flex-1 rounded border border-line px-2 py-1"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className="rounded bg-accent px-3 py-1 text-white disabled:opacity-50"
        >
          Search
        </button>
      </form>
      <ErrorBanner error={results.error ?? latest.error} onRetry={() => void results.refetch()} />
      {q && !runId && !latest.isPending && (
        <p className="text-sm text-ink-muted">No indexed run is available to search.</p>
      )}
      {results.isSuccess && results.data.length === 0 && (
        <p className="text-sm text-ink-muted">No matches.</p>
      )}
      {results.isSuccess && (
        <ul className="divide-y divide-line rounded border border-line bg-surface">
          {results.data.map((hit, index) => (
            <li key={String(hit.crop_id ?? index)} className="flex items-center gap-3 p-2 text-sm">
              {hit.crop_id && (
                <img
                  src={`/v1/crops/${encodeURIComponent(hit.crop_id)}/image`}
                  alt="Privacy-screened crop"
                  className="h-16 rounded"
                />
              )}
              <span className="text-ink-muted">
                {typeof (hit.similarity ?? hit.score) === "number"
                  ? `${(hit.similarity ?? hit.score)!.toFixed(3)} (not a probability)`
                  : ""}
              </span>
              {hit.source_id && (
                <Link
                  className="ml-auto text-accent"
                  to={`/review?video=${encodeURIComponent(hit.source_id)}`}
                >
                  Open video
                  {typeof hit.elapsed_seconds === "number"
                    ? ` at ${hit.elapsed_seconds.toFixed(1)}s`
                    : ""}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
