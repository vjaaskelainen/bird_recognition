import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { safeReturn, signIn } from "@/api/session";

export function SignIn() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(key);
      client.setQueryData(["session"], true);
      setKey("");
      navigate(safeReturn(params.get("return")), { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setError("That key is not valid.");
      } else if (caught instanceof ApiError && caught.code === "key_not_configured") {
        setError("The service has no API key configured, so sign-in is unavailable.");
      } else {
        setError("Sign-in failed. Check the connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-24 max-w-sm rounded border border-line bg-surface p-6">
      <h1 className="mb-4 text-lg font-semibold">Sign in</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          API key
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            className="rounded border border-line px-2 py-1"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || key.length === 0}
          className="rounded bg-accent px-3 py-1 text-white disabled:opacity-50"
        >
          Sign in
        </button>
      </form>
    </main>
  );
}
