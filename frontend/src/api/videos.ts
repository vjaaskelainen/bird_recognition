import { api, expectOk, unwrap } from "./client";
import { PAGE_SIZE, type Filters } from "@/lib/filters";

export function listVideos(filters: Filters) {
  return api
    .GET("/v1/videos", {
      params: {
        query: {
          status: filters.status,
          review: filters.review ?? undefined,
          folder: filters.folder || undefined,
          from: filters.from || undefined,
          to: filters.to || undefined,
          sort: filters.sort,
          order: filters.order,
          limit: PAGE_SIZE,
          offset: (filters.page - 1) * PAGE_SIZE,
        },
      },
    })
    .then(unwrap);
}

export function getVideo(sourceId: string) {
  return api
    .GET("/v1/videos/{source_id}", { params: { path: { source_id: sourceId } } })
    .then(unwrap);
}

export function getQueue(exclude: string[], limit = 3) {
  return api.GET("/v1/videos/queue", { params: { query: { limit, exclude } } }).then(unwrap);
}

export function submitReview(sourceId: string, body: import("./client").ReviewRequest) {
  return api
    .POST("/v1/videos/{source_id}/reviews", {
      params: { path: { source_id: sourceId } },
      body,
    })
    .then(unwrap);
}

export function undoReview(reviewId: string) {
  return api
    .POST("/v1/reviews/{review_id}/undo", {
      params: { path: { review_id: reviewId } },
    })
    .then(unwrap);
}

export function bulkConfirm(sourceIds: string[]) {
  return api
    .POST("/v1/reviews/bulk", { body: { source_ids: sourceIds, outcome: "confirmed" } })
    .then(unwrap);
}

export function getLayout(sourceId: string) {
  return api
    .GET("/v1/videos/{source_id}/contact-sheet/layout", {
      params: { path: { source_id: sourceId } },
    })
    .then(unwrap);
}

export function getPlayback(sourceId: string) {
  return api
    .GET("/v1/videos/{source_id}/playback", {
      params: { path: { source_id: sourceId } },
    })
    .then(unwrap);
}

export function setCorrection(
  cropId: string,
  body: {
    source_id: string;
    truth_kind: "species" | "out_of_list" | "unidentifiable";
    species_id?: string | null;
  },
) {
  return api
    .PUT("/v1/crops/{crop_id}/correction", {
      params: { path: { crop_id: cropId } },
      body,
    })
    .then(unwrap);
}

export function clearCorrection(cropId: string) {
  return api
    .DELETE("/v1/crops/{crop_id}/correction", {
      params: { path: { crop_id: cropId } },
    })
    .then(expectOk);
}

export const sheetUrl = (id: string) => `/v1/videos/${encodeURIComponent(id)}/contact-sheet`;
