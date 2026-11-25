import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getLayout, sheetUrl } from "@/api/videos";
import { UnfilteredMarker } from "@/components/Shell";

interface Props {
  sourceId: string;
  onPickTime?: (seconds: number) => void;
}

/** Contact sheet with SVG detection boxes; clicking a frame picks its time. */
export function ContactSheet({ sourceId, onPickTime }: Props) {
  const layout = useQuery({
    queryKey: ["layout", sourceId],
    queryFn: () => getLayout(sourceId),
    retry: false,
  });
  const [failed, setFailed] = useState(false);
  const data = layout.data;
  const rows = data ? Math.ceil(data.tiles.length / data.columns) : 0;
  const width = data ? data.columns * data.tile_width : 0;
  const height = data ? rows * data.tile_height : 0;

  return (
    <section
      aria-label="Contact sheet"
      data-testid="contact-sheet"
      className="rounded border border-line bg-surface p-2"
    >
      <div className="mb-1 flex items-center gap-2 text-xs">
        <UnfilteredMarker />
        <span className="text-ink-muted">Dashed boxes are below the animal threshold.</span>
      </div>
      {failed ? (
        <p role="alert" className="p-4 text-sm text-danger">
          The contact sheet is unavailable (source file missing or cache unavailable).
        </p>
      ) : (
        <div className="relative">
          <img
            src={sheetUrl(sourceId)}
            alt="Contact sheet of sampled frames"
            className="block w-full"
            onError={() => setFailed(true)}
          />
          {data && (
            <svg viewBox={`0 0 ${width} ${height}`} className="absolute inset-0 h-full w-full">
              {data.tiles.map((tile) => {
                const x = (tile.index % data.columns) * data.tile_width;
                const y = Math.floor(tile.index / data.columns) * data.tile_height;
                return (
                  <g
                    key={tile.index}
                    transform={`translate(${x} ${y})`}
                    onClick={() => onPickTime?.(tile.elapsed_seconds)}
                    className="cursor-pointer"
                  >
                    <rect width={data.tile_width} height={data.tile_height} fill="transparent" />
                    {tile.boxes.map((box, index) => (
                      <rect
                        key={index}
                        x={box.left * data.tile_width}
                        y={box.top * data.tile_height}
                        width={(box.right - box.left) * data.tile_width}
                        height={(box.bottom - box.top) * data.tile_height}
                        fill="none"
                        stroke={box.qualifies ? "#1a7f37" : "#b45309"}
                        strokeWidth={2}
                        strokeDasharray={box.qualifies ? undefined : "4 3"}
                      >
                        <title>{`${box.category} ${box.confidence.toFixed(2)}`}</title>
                      </rect>
                    ))}
                    <text
                      x={4}
                      y={data.tile_height - 4}
                      fontSize={12}
                      fill="#fff"
                      stroke="#000"
                      strokeWidth={0.5}
                    >
                      {tile.elapsed_seconds.toFixed(1)}s
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
      )}
    </section>
  );
}
