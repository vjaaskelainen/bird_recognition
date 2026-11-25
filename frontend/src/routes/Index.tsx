import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { getQueue } from "@/api/videos";

export function Index() {
  const queue = useQuery({ queryKey: ["queue-probe"], queryFn: () => getQueue([], 1) });
  if (queue.isPending) return <p className="text-sm text-ink-muted">Loading…</p>;
  if (queue.isError) return <Navigate to="/videos" replace />;
  return <Navigate to={queue.data.remaining > 0 ? "/review" : "/videos"} replace />;
}
