import { useQuery } from "@tanstack/react-query";
import { forwardRef } from "react";
import { getPlayback } from "@/api/videos";
import { UnfilteredMarker } from "@/components/Shell";

const MESSAGES: Record<string, string> = {
  converting: "Preparing a browser-playable copy…",
  failed: "Playback conversion failed for this video.",
  unavailable: "This video cannot be played in the browser.",
  source_missing: "The source file is missing.",
  not_started: "Starting conversion…",
};

interface Props {
  sourceId: string;
}

/** Native player; polls every 2 s while conversion runs. */
export const Player = forwardRef<HTMLVideoElement, Props>(function Player({ sourceId }, ref) {
  const playback = useQuery({
    queryKey: ["playback", sourceId],
    queryFn: () => getPlayback(sourceId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "converting" || status === "not_started" ? 2000 : false;
    },
  });
  const status = playback.data?.status;
  return (
    <section aria-label="Player" className="rounded border border-line bg-surface p-2">
      <div className="mb-1">
        <UnfilteredMarker />
      </div>
      {status === "ready" && playback.data?.url ? (
        <video ref={ref} src={playback.data.url} controls className="w-full" />
      ) : (
        <p role="status" className="p-4 text-sm text-ink-muted">
          {playback.isError
            ? "Playback status could not be loaded."
            : status
              ? (playback.data?.reason ?? MESSAGES[status] ?? status)
              : "Loading…"}
        </p>
      )}
    </section>
  );
});
