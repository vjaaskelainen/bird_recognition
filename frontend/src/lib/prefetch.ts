import type { QueryClient } from "@tanstack/react-query";
import type { VideoDetail } from "@/api/client";
import { getLayout, sheetUrl } from "@/api/videos";

function warmImage(url: string): void {
  const image = new Image();
  image.src = url;
}

/** Warm sheet, layout and crop images of the next queue items (HTTP + Query cache). */
export function prefetchNext(client: QueryClient, items: VideoDetail[], ahead = 2): void {
  for (const item of items.slice(0, ahead)) {
    if (!item.source_id) continue;
    const id = item.source_id;
    client.setQueryData(["video", id], item);
    void client.prefetchQuery({ queryKey: ["layout", id], queryFn: () => getLayout(id) });
    warmImage(sheetUrl(id));
    for (const crop of item.crops) warmImage(crop.image_url);
  }
}

/** Items to prefetch: everything after the current one, never skipped ones. */
export function upcoming(
  items: VideoDetail[],
  currentId: string | null,
  skipped: ReadonlySet<string>,
): VideoDetail[] {
  return items.filter(
    (item) => item.source_id && item.source_id !== currentId && !skipped.has(item.source_id),
  );
}
