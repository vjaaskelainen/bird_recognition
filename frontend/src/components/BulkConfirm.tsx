import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { bulkConfirm, sheetUrl } from "@/api/videos";
import { ErrorBanner, UnfilteredMarker } from "@/components/Shell";

const SAMPLE = 12;

/** Confirms automatic no-animal results only after showing sample sheets and the count. */
export function BulkConfirm({ sourceIds, total }: { sourceIds: string[]; total: number }) {
  const [open, setOpen] = useState(false);
  const [ack, setAck] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => bulkConfirm(sourceIds),
    onSuccess: () => {
      setOpen(false);
      setAck(false);
      void client.invalidateQueries();
    },
  });
  const sample = sourceIds.slice(0, SAMPLE);

  if (!open) {
    return (
      <button
        type="button"
        data-testid="bulk-open"
        disabled={sourceIds.length === 0}
        onClick={() => setOpen(true)}
        className="rounded border border-line bg-surface px-3 py-1 text-sm disabled:opacity-50"
      >
        Bulk confirm shown no-animal videos
      </button>
    );
  }
  return (
    <section aria-label="Bulk confirm" className="my-3 rounded border border-line bg-surface p-3">
      <p className="mb-2 text-sm">
        Confirm <strong>{total}</strong> unreviewed no-animal videos? Showing {sample.length} sample
        sheets. <UnfilteredMarker />
      </p>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {sample.map((id) => (
          <img
            key={id}
            src={sheetUrl(id)}
            alt="Sample contact sheet"
            loading="lazy"
            className="w-full rounded border border-line"
          />
        ))}
      </div>
      <label className="mb-2 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />I
        checked the samples and want to confirm all {total}.
      </label>
      <ErrorBanner error={mutation.error} />
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="bulk-confirm"
          disabled={!ack || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="rounded bg-accent px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          Confirm {total}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm underline">
          Cancel
        </button>
      </div>
    </section>
  );
}
