import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Search } from "@/routes/Search";

function mockFetch(handler: (url: string) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) =>
      handler(typeof input === "string" ? input : input.url),
    ),
  );
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status < 400 ? "application/json" : "application/problem+json" },
  });

function renderSearch() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/search?run=11111111-1111-4111-8111-111111111111"]}>
        <Search />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

async function search() {
  await userEvent.type(screen.getByLabelText("Query"), "robin");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
}

describe("Search", () => {
  it("always shows the caveat and lists results with video links", async () => {
    mockFetch(() =>
      json({ results: [{ crop_id: "c1", similarity: 0.5, source_id: "s1", elapsed_seconds: 2 }] }),
    );
    renderSearch();
    expect(screen.getByText(/Not a probability/)).toBeInTheDocument();
    await search();
    const link = await screen.findByRole("link", { name: /Open video/ });
    expect(link).toHaveAttribute("href", "/review?video=s1");
    expect(screen.getByText(/Not a probability/)).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    mockFetch(() => json({ results: [] }));
    renderSearch();
    await search();
    expect(await screen.findByText("No matches.")).toBeInTheDocument();
  });

  it("shows an error", async () => {
    mockFetch(() => json({ status: 503, code: "database_unavailable", detail: "down" }, 503));
    renderSearch();
    await search();
    expect(await screen.findByRole("alert")).toHaveTextContent("down");
  });
});
