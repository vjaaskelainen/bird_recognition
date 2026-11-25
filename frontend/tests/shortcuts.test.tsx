import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useShortcuts } from "@/lib/shortcuts";

function Harness({ calls }: { calls: Record<string, () => void> }) {
  useShortcuts(calls);
  return <input aria-label="note" />;
}

describe("shortcuts", () => {
  it("maps keys to actions", async () => {
    const calls = {
      confirm: vi.fn(),
      correct: vi.fn(),
      skip: vi.fn(),
      undo: vi.fn(),
      player: vi.fn(),
      next: vi.fn(),
      previous: vi.fn(),
    };
    render(<Harness calls={calls} />);
    await userEvent.keyboard("ceszp{ArrowRight}{ArrowLeft}");
    for (const call of Object.values(calls)) expect(call).toHaveBeenCalledTimes(1);
  });

  it("is disabled while typing", async () => {
    const confirm = vi.fn();
    render(<Harness calls={{ confirm }} />);
    await userEvent.click(screen.getByLabelText("note"));
    await userEvent.keyboard("c");
    expect(confirm).not.toHaveBeenCalled();
  });
});
