import { api, expectOk } from "./client";

/** True when the browser already holds a valid session cookie. */
export async function hasSession(): Promise<boolean> {
  const result = await api.GET("/v1/session");
  return result.response.status === 204;
}

/** Exchange the key for a cookie; the key is never stored by the UI. */
export async function signIn(key: string): Promise<void> {
  const result = await api.POST("/v1/session", { body: { key } });
  expectOk(result);
}

export async function signOut(): Promise<void> {
  await api.DELETE("/v1/session");
}

/** Only same-origin paths are valid return targets. */
export function safeReturn(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}
