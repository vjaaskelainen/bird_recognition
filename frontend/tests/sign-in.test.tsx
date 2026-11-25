import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { SignIn } from "@/routes/SignIn";

const signIn = vi.fn();
vi.mock("@/api/session", async (original) => ({
  ...(await original<typeof import("@/api/session")>()),
  signIn: (key: string) => signIn(key),
}));

function renderAt(url: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/sign-in" element={<SignIn />} />
          <Route path="*" element={<div>landed</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SignIn", () => {
  beforeEach(() => {
    signIn.mockReset();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("shows an error for a wrong key", async () => {
    signIn.mockRejectedValue(new ApiError(401, "unauthorized", "no"));
    renderAt("/sign-in");
    await userEvent.type(screen.getByLabelText("API key"), "bad");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not valid");
  });

  it("redirects to the return URL without persisting the key", async () => {
    signIn.mockResolvedValue(undefined);
    renderAt("/sign-in?return=%2Fvideos%3Fpage%3D2");
    await userEvent.type(screen.getByLabelText("API key"), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByText("landed")).toBeInTheDocument());
    expect(signIn).toHaveBeenCalledWith("secret");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});
