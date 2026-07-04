import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TourOverlay } from "./TourOverlay";
import type { TourStep } from "./tourSteps";

const step = (over: Partial<TourStep> = {}): TourStep => ({
  key: "welcome",
  target: null,
  copyKey: "tour.welcome",
  ...over,
});

describe("TourOverlay", () => {
  it("renders a modal dialog with the step copy and progress", () => {
    render(
      <TourOverlay step={step()} index={0} total={6} onNext={vi.fn()} onBack={vi.fn()} onSkip={vi.fn()} />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("1 / 6")).toBeInTheDocument();
  });

  it("Escape skips", () => {
    const onSkip = vi.fn();
    render(
      <TourOverlay step={step()} index={0} total={6} onNext={vi.fn()} onBack={vi.fn()} onSkip={onSkip} />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onSkip).toHaveBeenCalled();
  });

  it("hides Back on the first step and shows Done on the last", () => {
    const { rerender } = render(
      <TourOverlay step={step()} index={0} total={2} onNext={vi.fn()} onBack={vi.fn()} onSkip={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /back/i })).toBeNull();
    rerender(
      <TourOverlay step={step({ key: "authbar", target: "authbar" })} index={1} total={2}
        onNext={vi.fn()} onBack={vi.fn()} onSkip={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /done/i })).toBeInTheDocument();
  });

  it("spotlights the data-tour target when present", () => {
    const anchor = document.createElement("div");
    anchor.setAttribute("data-tour", "map");
    document.body.appendChild(anchor);
    render(
      <TourOverlay step={step({ key: "map", target: "map" })} index={1} total={6}
        onNext={vi.fn()} onBack={vi.fn()} onSkip={vi.fn()} />,
    );
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    anchor.remove();
  });

  it("falls back to full-dim when the target is missing", () => {
    render(
      <TourOverlay step={step({ key: "map", target: "map" })} index={1} total={6}
        onNext={vi.fn()} onBack={vi.fn()} onSkip={vi.fn()} />,
    );
    expect(document.querySelector(".tour-spotlight")).toBeNull();
    expect(document.querySelector(".tour-dim")).not.toBeNull();
  });
});
