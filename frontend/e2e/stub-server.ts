// Minimal stand-in for the API plus the built bundle, used by the smoke test.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const dist = join(import.meta.dirname, "..", "dist");
const TYPES: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
};
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

interface Video {
  source_id: string;
  path_id: string;
  path: string;
  basename: string;
  folder: string;
  capture_start: string;
  status: "no_animals";
  failure_reason: null;
  crop_count: number;
  top_label: null;
  run_id: string;
  ingested_at: string;
  settings: { interval: number; animal_threshold: number };
  settings_differ: boolean;
  review_state: "unreviewed" | "confirmed" | "corrected";
  playback_status: "not_started";
  source_available: boolean;
}

const videos: Video[] = ["a", "b", "c"].map((name) => ({
  source_id: `src-${name}`,
  path_id: `path-${name}`,
  path: `/clips/${name}.mp4`,
  basename: `${name}.mp4`,
  folder: "/clips",
  capture_start: "2026-01-01T10:00:00",
  status: "no_animals",
  failure_reason: null,
  crop_count: 0,
  top_label: null,
  run_id: "run-1",
  ingested_at: "2026-01-02T00:00:00",
  settings: { interval: 1, animal_threshold: 0.5 },
  settings_differ: false,
  review_state: "unreviewed",
  playback_status: "not_started",
  source_available: true,
}));
const reviews = new Map<string, { source_id: string; previous: Video["review_state"] }>();
let counter = 0;
let signedIn = false;

const detail = (video: Video) => ({
  ...video,
  detection_counts: {},
  crops: [],
  current_review: null,
  review_history: [],
});
const pending = (excluded: string[]) =>
  videos.filter((v) => v.review_state === "unreviewed" && !excluded.includes(v.source_id));

function send(res: import("node:http").ServerResponse, status: number, body?: unknown) {
  if (body === undefined) {
    res.writeHead(status).end();
    return;
  }
  res.writeHead(status, {
    "content-type": status < 400 ? "application/json" : "application/problem+json",
  });
  res.end(JSON.stringify(body));
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://stub");
  const path = url.pathname;
  const chunks: Buffer[] = [];
  req.on("data", (chunk: Buffer) => chunks.push(chunk));
  req.on("end", () => {
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
    if (path === "/v1/health") return send(res, 200, { status: "ok" });
    if (path === "/v1/session") {
      if (req.method === "POST") {
        if (body.key !== "secret")
          return send(res, 401, { status: 401, code: "unauthorized", detail: "no" });
        signedIn = true;
        return send(res, 204);
      }
      if (req.method === "DELETE") {
        signedIn = false;
        return send(res, 204);
      }
      return signedIn
        ? send(res, 204)
        : send(res, 401, { status: 401, code: "unauthorized", detail: "no" });
    }
    if (path.startsWith("/v1/")) {
      if (!signedIn) return send(res, 401, { status: 401, code: "unauthorized", detail: "no" });
      if (path === "/v1/videos") {
        return send(res, 200, { items: videos, limit: 50, offset: 0, total: videos.length });
      }
      if (path === "/v1/videos/queue") {
        const excluded = url.searchParams.getAll("exclude");
        const items = pending(excluded);
        return send(res, 200, { items: items.map(detail), remaining: items.length });
      }
      const sheet = path.match(/^\/v1\/videos\/([^/]+)\/contact-sheet(\/layout)?$/);
      if (sheet) {
        if (sheet[2])
          return send(res, 200, { columns: 1, tile_width: 1, tile_height: 1, tiles: [] });
        res.writeHead(200, { "content-type": "image/png" }).end(PIXEL);
        return;
      }
      const reviewPost = path.match(/^\/v1\/videos\/([^/]+)\/reviews$/);
      if (reviewPost && req.method === "POST") {
        const video = videos.find((v) => v.source_id === reviewPost[1]);
        if (!video) return send(res, 404, { status: 404, code: "not_found", detail: "no" });
        const id = `rev-${++counter}`;
        reviews.set(id, { source_id: video.source_id, previous: video.review_state });
        video.review_state = body.outcome;
        return send(res, 201, {
          review_id: id,
          source_id: video.source_id,
          outcome: body.outcome,
          correction_kind: body.correction_kind ?? null,
          species: body.species ?? [],
          missed_times: body.missed_times ?? [],
          note: body.note ?? null,
          auto_result: {},
          created_at: "2026-01-03T00:00:00",
          bulk_id: null,
          undone: false,
        });
      }
      const undo = path.match(/^\/v1\/reviews\/([^/]+)\/undo$/);
      if (undo) {
        const record = reviews.get(undo[1] ?? "");
        const video = videos.find((v) => v.source_id === record?.source_id);
        if (!record || !video)
          return send(res, 404, { status: 404, code: "not_found", detail: "no" });
        video.review_state = record.previous;
        return send(res, 200, {
          review_id: undo[1],
          source_id: video.source_id,
          outcome: "confirmed",
          correction_kind: null,
          species: [],
          missed_times: [],
          note: null,
          auto_result: {},
          created_at: "2026-01-03T00:00:00",
          bulk_id: null,
          undone: true,
        });
      }
      const single = path.match(/^\/v1\/videos\/([^/]+)$/);
      const found = videos.find((v) => v.source_id === single?.[1]);
      if (found) return send(res, 200, detail(found));
      return send(res, 404, { status: 404, code: "not_found", detail: "no" });
    }
    const file = normalize(join(dist, path === "/" ? "index.html" : path));
    const served = file.startsWith(dist) && existsSync(file) ? file : join(dist, "index.html");
    res.writeHead(200, { "content-type": TYPES[extname(served)] ?? "application/octet-stream" });
    res.end(readFileSync(served));
  });
});

server.listen(4173, "127.0.0.1");
