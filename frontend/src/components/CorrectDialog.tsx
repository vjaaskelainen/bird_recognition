import { useEffect, useState } from "react";
import type { ReviewRequest } from "@/api/client";

export type Draft = Pick<ReviewRequest, "correction_kind" | "species" | "missed_times" | "note">;

interface Props {
  open: boolean;
  suggestedTime: number | null;
  initial?: Draft;
  error?: string | null;
  busy?: boolean;
  onSubmit: (draft: Draft) => void;
  onCancel: () => void;
  onDraftChange?: (draft: Draft) => void;
}

type Kind = "no_animal" | "animal_missed" | "species_present";

/** Correction form; its state is lifted via onDraftChange so failures keep input. */
export function CorrectDialog({
  open,
  suggestedTime,
  initial,
  error,
  busy,
  onSubmit,
  onCancel,
  onDraftChange,
}: Props) {
  const [kind, setKind] = useState<Kind>((initial?.correction_kind as Kind) ?? "no_animal");
  const [times, setTimes] = useState<string[]>(initial?.missed_times?.map(String) ?? []);
  const [species, setSpecies] = useState((initial?.species ?? []).join(", "));
  const [note, setNote] = useState(initial?.note ?? "");

  useEffect(() => {
    if (suggestedTime === null) return;
    setKind("animal_missed");
    setTimes((current) => {
      const value = suggestedTime.toFixed(1);
      return current.includes(value) ? current : [...current, value];
    });
  }, [suggestedTime]);

  const parsedTimes = times.map((value) => Number(value));
  const speciesIds = species
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const valid =
    kind === "no_animal" ||
    (kind === "animal_missed" &&
      parsedTimes.length > 0 &&
      parsedTimes.every((v) => Number.isFinite(v) && v >= 0)) ||
    (kind === "species_present" && speciesIds.length > 0);

  const draft: Draft = {
    correction_kind: kind,
    species: kind === "species_present" ? speciesIds : [],
    missed_times: kind === "animal_missed" ? parsedTimes : [],
    note: note.trim() || null,
  };
  useEffect(() => {
    onDraftChange?.(draft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, times, species, note]);

  if (!open) return null;
  return (
    <form
      role="dialog"
      aria-label="Correct review"
      className="my-3 rounded border border-line bg-surface p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) onSubmit(draft);
      }}
    >
      <fieldset className="mb-2 flex flex-col gap-1">
        <legend className="mb-1 font-medium">What is wrong?</legend>
        <label>
          <input
            type="radio"
            name="kind"
            checked={kind === "no_animal"}
            onChange={() => setKind("no_animal")}
          />{" "}
          No animal here
        </label>
        <label>
          <input
            type="radio"
            name="kind"
            checked={kind === "animal_missed"}
            onChange={() => setKind("animal_missed")}
          />{" "}
          Animal missed
        </label>
        <label>
          <input
            type="radio"
            name="kind"
            checked={kind === "species_present"}
            onChange={() => setKind("species_present")}
          />{" "}
          Species or category present
        </label>
      </fieldset>
      {kind === "animal_missed" && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {times.map((value, index) => (
            <label key={index} className="flex items-center gap-1">
              Time (s)
              <input
                value={value}
                onChange={(event) =>
                  setTimes(times.map((item, i) => (i === index ? event.target.value : item)))
                }
                className="w-20 rounded border border-line px-1"
              />
              <button
                type="button"
                aria-label="Remove time"
                onClick={() => setTimes(times.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </label>
          ))}
          <button type="button" className="underline" onClick={() => setTimes([...times, ""])}>
            Add time
          </button>
        </div>
      )}
      {kind === "species_present" && (
        <label className="mb-2 flex flex-col">
          Species or category ids (comma separated)
          <input
            value={species}
            onChange={(event) => setSpecies(event.target.value)}
            className="rounded border border-line px-2 py-1"
          />
        </label>
      )}
      <label className="mb-2 flex flex-col">
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          className="rounded border border-line px-2 py-1"
        />
      </label>
      {error && (
        <p role="alert" className="mb-2 text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!valid || busy}
          className="rounded bg-accent px-3 py-1 text-white disabled:opacity-50"
        >
          Save correction
        </button>
        <button type="button" onClick={onCancel} className="underline">
          Cancel
        </button>
      </div>
    </form>
  );
}
