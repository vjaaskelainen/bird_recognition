import { cn } from "@/lib/cn";
import type { VideoSummary } from "@/api/client";

const LABELS: Record<VideoSummary["status"], string> = {
  not_ingested: "Not ingested",
  no_animals: "No animals",
  animals: "Animals",
  failed: "Failed",
};

const TONES: Record<VideoSummary["status"], string> = {
  not_ingested: "bg-surface-muted text-ink-muted",
  no_animals: "bg-blue-100 text-accent",
  animals: "bg-green-100 text-ok",
  failed: "bg-red-100 text-danger",
};

export function StatusBadge({
  video,
}: {
  video: Pick<VideoSummary, "status" | "review_state" | "settings_differ">;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        data-testid="status-badge"
        className={cn("rounded px-2 py-0.5 text-xs font-medium", TONES[video.status])}
      >
        {LABELS[video.status]}
      </span>
      <span className="rounded bg-surface-muted px-2 py-0.5 text-xs text-ink-muted">
        {video.review_state}
      </span>
      {video.settings_differ && (
        <span
          title="Ingested with settings that differ from the current configuration"
          className="rounded bg-amber-100 px-2 py-0.5 text-xs text-warn"
        >
          settings differ
        </span>
      )}
    </span>
  );
}
