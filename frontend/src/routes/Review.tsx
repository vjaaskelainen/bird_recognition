import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, type ReviewRequest, type VideoDetail } from "@/api/client";
import { getQueue, getVideo, submitReview, undoReview } from "@/api/videos";
import { ContactSheet } from "@/components/ContactSheet";
import { CorrectDialog, type Draft } from "@/components/CorrectDialog";
import { CropStrip } from "@/components/CropStrip";
import { Player } from "@/components/Player";
import { ErrorBanner } from "@/components/Shell";
import { StatusBadge } from "@/components/StatusBadge";
import { prefetchNext, upcoming } from "@/lib/prefetch";
import { useShortcuts } from "@/lib/shortcuts";

export function Review() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const requested = params.get("video");
  const [skipped, setSkipped] = useState<string[]>([]);
  const [last, setLast] = useState<{ reviewId: string; sourceId: string } | null>(null);
  const [showCorrect, setShowCorrect] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);
  const [suggestedTime, setSuggestedTime] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | undefined>();
  const seen = useRef<string[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);

  const queue = useQuery({
    queryKey: ["queue", skipped.join(",")],
    queryFn: () => getQueue(skipped, 3),
  });
  const direct = useQuery({
    queryKey: ["video", requested],
    queryFn: () => getVideo(requested as string),
    enabled: requested !== null,
  });

  const current: VideoDetail | undefined = requested ? direct.data : queue.data?.items[0];
  const currentId = current?.source_id ?? null;
  const loading = requested ? direct.isPending : queue.isPending;
  const loadError = requested ? direct.error : queue.error;

  useEffect(() => {
    if (currentId && seen.current.at(-1) !== currentId) seen.current.push(currentId);
    setShowCorrect(false);
    setShowPlayer(false);
    setSuggestedTime(null);
    setDraft(undefined);
  }, [currentId]);

  useEffect(() => {
    if (queue.data) {
      prefetchNext(client, upcoming(queue.data.items, currentId, new Set(skipped)));
    }
  }, [queue.data, currentId, skipped, client]);

  const advance = () => {
    if (requested) setParams({});
    void client.invalidateQueries({ queryKey: ["queue"] });
    void client.invalidateQueries({ queryKey: ["queue-probe"] });
    void client.invalidateQueries({ queryKey: ["videos"] });
  };

  const review = useMutation({
    mutationFn: (body: ReviewRequest) => submitReview(currentId as string, body),
    onSuccess: (saved) => {
      setLast({ reviewId: saved.review_id, sourceId: saved.source_id });
      setShowCorrect(false);
      setDraft(undefined);
      void client.invalidateQueries({ queryKey: ["video", saved.source_id] });
      advance();
    },
  });
  const undo = useMutation({
    mutationFn: (reviewId: string) => undoReview(reviewId),
    onSuccess: () => {
      const target = last?.sourceId;
      setLast(null);
      void client.invalidateQueries();
      if (target) navigate(`/review?video=${encodeURIComponent(target)}`);
    },
  });

  const confirm = () => {
    if (currentId && !review.isPending) review.mutate({ outcome: "confirmed" });
  };
  const skip = () => {
    if (!currentId) return;
    setSkipped((items) => [...items, currentId]);
    if (requested) setParams({});
  };
  const previous = () => {
    seen.current.pop();
    const target = seen.current.pop();
    if (target) navigate(`/review?video=${encodeURIComponent(target)}`);
  };
  const togglePlayer = () => setShowPlayer((value) => !value);
  const openCorrect = () => {
    const time = videoRef.current?.currentTime;
    if (showPlayer && time !== undefined && time > 0) setSuggestedTime(time);
    setShowCorrect(true);
  };

  useShortcuts({
    confirm,
    correct: openCorrect,
    skip,
    undo: () => last && undo.mutate(last.reviewId),
    player: togglePlayer,
    next: skip,
    previous,
  });

  const retry = () => {
    if (review.variables) review.mutate(review.variables);
  };
  const submitError =
    review.error instanceof ApiError
      ? review.error.message
      : review.error
        ? "The review could not be saved."
        : null;

  if (loading) return <p className="text-sm text-ink-muted">Loading…</p>;

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <h1 className="text-lg font-semibold">Review</h1>
        <button
          type="button"
          data-testid="action-undo"
          disabled={!last || undo.isPending}
          onClick={() => last && undo.mutate(last.reviewId)}
          className="ml-auto rounded border border-line px-3 py-1 text-sm disabled:opacity-50"
        >
          Undo (Z)
        </button>
      </div>
      <ErrorBanner error={loadError ?? undo.error} />
      {!current ? (
        <p className="rounded border border-line bg-surface p-4 text-sm text-ink-muted">
          Nothing to review.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <strong>{current.basename}</strong>
            <span className="text-ink-muted">{current.capture_start ?? "unknown time"}</span>
            <StatusBadge video={current} />
            <span className="text-ink-muted">
              {current.crop_count} crops{current.top_label ? ` · ${current.top_label}` : ""}
            </span>
          </div>
          <p className="text-xs text-ink-muted">
            Interval {current.settings.interval ?? "?"}s · animal threshold{" "}
            {current.settings.animal_threshold ?? "?"}
          </p>
          {current.settings_differ && (
            <p
              role="alert"
              className="rounded border border-warn bg-amber-50 p-2 text-sm text-warn"
            >
              This video was ingested with settings that differ from the current configuration.
            </p>
          )}
          {current.failure_reason && (
            <p className="text-sm text-danger">Failure: {current.failure_reason}</p>
          )}
          <ContactSheet
            sourceId={current.source_id as string}
            onPickTime={(t) => {
              setSuggestedTime(t);
              setShowCorrect(true);
            }}
          />
          {showPlayer && <Player ref={videoRef} sourceId={current.source_id as string} />}
          <CropStrip sourceId={current.source_id as string} crops={current.crops} />
          <ErrorBanner error={review.error ? new Error(submitError ?? "") : null} onRetry={retry} />
          <CorrectDialog
            key={currentId}
            open={showCorrect}
            suggestedTime={suggestedTime}
            initial={draft}
            busy={review.isPending}
            onDraftChange={setDraft}
            onCancel={() => setShowCorrect(false)}
            onSubmit={(value) => review.mutate({ outcome: "corrected", ...value })}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              data-testid="action-confirm"
              onClick={confirm}
              disabled={review.isPending}
              className="rounded bg-ok px-3 py-1 text-white disabled:opacity-50"
            >
              Confirm (C)
            </button>
            <button
              type="button"
              data-testid="action-correct"
              onClick={openCorrect}
              className="rounded bg-accent px-3 py-1 text-white"
            >
              Correct (E)
            </button>
            <button
              type="button"
              data-testid="action-skip"
              onClick={skip}
              className="rounded border border-line px-3 py-1"
            >
              Skip (S)
            </button>
            <button
              type="button"
              onClick={togglePlayer}
              className="rounded border border-line px-3 py-1"
            >
              {showPlayer ? "Hide player (P)" : "Open player (P)"}
            </button>
            <button
              type="button"
              onClick={previous}
              className="rounded border border-line px-3 py-1"
            >
              ← Previous
            </button>
          </div>
          {current.review_history.length > 0 && (
            <section aria-label="Review history" className="text-sm">
              <h2 className="mb-1 font-medium">Review history</h2>
              <ul className="list-disc pl-5 text-ink-muted">
                {current.review_history.map((item) => (
                  <li key={item.review_id}>
                    {item.created_at}: {item.outcome}
                    {item.correction_kind ? ` (${item.correction_kind})` : ""}
                    {item.undone ? " — undone" : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
