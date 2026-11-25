import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type VideoSummary = Schemas["VideoSummary"];
export type VideoDetail = Schemas["VideoDetail"];
export type VideoCrop = Schemas["VideoCrop"];
export type Review = Schemas["Review"];
export type ReviewRequest = Schemas["ReviewRequest"];
export type SheetLayout = Schemas["SheetLayout"];
export type Playback = Schemas["Playback"];

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  fetch: (request) => globalThis.fetch(request),
});

type Handler = () => void;
let onUnauthorized: Handler | null = null;

/** Register how the app reacts to a 401 (the router navigates to sign-in). */
export function setUnauthorizedHandler(handler: Handler | null): void {
  onUnauthorized = handler;
}

api.use({
  onResponse({ response }) {
    if (response.status === 401 && onUnauthorized) onUnauthorized();
    return undefined;
  },
});

/** Error carrying the stable problem+json code of a failed API call. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

interface Problem {
  status?: number;
  code?: string;
  detail?: string;
}

/** Return data or throw an ApiError so React Query can surface failures. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const problem = (result.error ?? {}) as Problem;
    throw new ApiError(
      result.response.status,
      problem.code ?? "error",
      problem.detail ?? `Request failed (${result.response.status})`,
    );
  }
  return result.data;
}

/** Same as unwrap for 204 responses without a body. */
export function expectOk(result: { error?: unknown; response: Response }): void {
  if (result.error !== undefined || !result.response.ok) {
    const problem = (result.error ?? {}) as Problem;
    throw new ApiError(
      result.response.status,
      problem.code ?? "error",
      problem.detail ?? `Request failed (${result.response.status})`,
    );
  }
}
