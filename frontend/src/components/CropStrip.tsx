import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { VideoCrop } from "@/api/client";
import { clearCorrection, setCorrection } from "@/api/videos";
import { ErrorBanner } from "@/components/Shell";

interface Props {
  sourceId: string;
  crops: VideoCrop[];
}

function label(crop: VideoCrop): string {
  const current = crop.current_correction;
  if (!current) return "not labelled";
  if (current.truth_kind === "species") return current.species_id ?? "species";
  return current.truth_kind === "out_of_list" ? "not in list" : "unidentifiable";
}

/** Privacy-screened crops with immediate per-crop truth labels. */
export function CropStrip({ sourceId, crops }: Props) {
  const client = useQueryClient();
  const [species, setSpecies] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: async (args: {
      cropId: string;
      kind: "species" | "out_of_list" | "unidentifiable" | "clear";
      speciesId?: string;
    }) =>
      args.kind === "clear"
        ? clearCorrection(args.cropId)
        : setCorrection(args.cropId, {
            source_id: sourceId,
            truth_kind: args.kind,
            species_id: args.kind === "species" ? args.speciesId : null,
          }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["video", sourceId] }),
  });

  if (crops.length === 0) {
    return <p className="text-sm text-ink-muted">No crops for this video.</p>;
  }
  return (
    <section aria-label="Crops">
      <ErrorBanner error={mutation.error} />
      <ul className="flex flex-wrap gap-3">
        {crops.map((crop) => (
          <li key={crop.crop_id} className="w-44 rounded border border-line bg-surface p-2 text-xs">
            <img src={crop.image_url} alt="Privacy-screened crop" className="mb-1 w-full rounded" />
            <div className="mb-1 text-ink-muted">
              {crop.elapsed_seconds.toFixed(1)}s · {crop.confidence.toFixed(2)} (not a probability)
            </div>
            <div className="mb-1 font-medium">{label(crop)}</div>
            <div className="flex gap-1">
              <input
                aria-label="Species id"
                value={species[crop.crop_id] ?? ""}
                onChange={(event) => setSpecies({ ...species, [crop.crop_id]: event.target.value })}
                className="min-w-0 flex-1 rounded border border-line px-1"
              />
              <button
                type="button"
                disabled={!species[crop.crop_id]?.trim()}
                onClick={() =>
                  mutation.mutate({
                    cropId: crop.crop_id,
                    kind: "species",
                    speciesId: species[crop.crop_id]?.trim(),
                  })
                }
                className="rounded border border-line px-1 disabled:opacity-50"
              >
                Set
              </button>
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              <button
                type="button"
                className="rounded border border-line px-1"
                onClick={() => mutation.mutate({ cropId: crop.crop_id, kind: "out_of_list" })}
              >
                Not in list
              </button>
              <button
                type="button"
                className="rounded border border-line px-1"
                onClick={() => mutation.mutate({ cropId: crop.crop_id, kind: "unidentifiable" })}
              >
                Unidentifiable
              </button>
              {crop.current_correction && (
                <button
                  type="button"
                  className="rounded border border-line px-1"
                  onClick={() => mutation.mutate({ cropId: crop.crop_id, kind: "clear" })}
                >
                  Clear
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
