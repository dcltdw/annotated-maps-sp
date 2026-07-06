import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_SEEN_KEY, TOUR_STEPS } from "./tourSteps";
import { useTour } from "./useTour";

const opts = (over: Partial<Parameters<typeof useTour>[0]> = {}) => ({
  ready: true,
  loggedOut: true,
  hasSwitchTarget: true,
  hasShowcase: true,
  onEffect: vi.fn(),
  ...over,
});

describe("useTour", () => {
  beforeEach(() => localStorage.clear());

  it("auto-starts on first visit and marks seen immediately", () => {
    const { result } = renderHook(() => useTour(opts()));
    expect(result.current.active).toBe(true);
    expect(result.current.index).toBe(0);
    expect(localStorage.getItem(TOUR_SEEN_KEY)).not.toBeNull();
  });

  it("does not auto-start when already seen", () => {
    localStorage.setItem(TOUR_SEEN_KEY, "1");
    const { result } = renderHook(() => useTour(opts()));
    expect(result.current.active).toBe(false);
  });

  it("does not auto-start until ready, then starts when ready flips", () => {
    const { result, rerender } = renderHook((p) => useTour(p), {
      initialProps: opts({ ready: false }),
    });
    expect(result.current.active).toBe(false);
    rerender(opts({ ready: true }));
    expect(result.current.active).toBe(true);
  });

  it("does not auto-start for logged-in users", () => {
    const { result } = renderHook(() => useTour(opts({ loggedOut: false })));
    expect(result.current.active).toBe(false);
    expect(localStorage.getItem(TOUR_SEEN_KEY)).toBeNull(); // unseen — they may log out later
  });

  it("start() always works (replay), even when seen", () => {
    localStorage.setItem(TOUR_SEEN_KEY, "1");
    const { result } = renderHook(() => useTour(opts()));
    act(() => result.current.start());
    expect(result.current.active).toBe(true);
    expect(result.current.index).toBe(0);
  });

  it("walks forward and back through all steps and finishes", () => {
    const { result } = renderHook(() => useTour(opts()));
    expect(result.current.total).toBe(TOUR_STEPS.length);
    act(() => result.current.next());
    expect(result.current.index).toBe(1);
    act(() => result.current.back());
    expect(result.current.index).toBe(0);
    for (let i = 0; i < TOUR_STEPS.length; i++) act(() => result.current.next());
    expect(result.current.active).toBe(false); // next past the end finishes
  });

  it("skip() closes immediately", () => {
    const { result } = renderHook(() => useTour(opts()));
    act(() => result.current.skip());
    expect(result.current.active).toBe(false);
  });

  it("fires effects once on entering effect-carrying steps", () => {
    const onEffect = vi.fn();
    const { result } = renderHook(() => useTour(opts({ onEffect })));
    // step 1 (map intro) carries reset-persona; walk to it
    act(() => result.current.next());
    expect(onEffect).toHaveBeenCalledWith("reset-persona");
    act(() => result.current.next()); // switcher step, no effect
    act(() => result.current.next()); // switch step
    expect(onEffect).toHaveBeenCalledWith("switch-persona");
    act(() => result.current.next()); // panel step
    expect(onEffect).toHaveBeenCalledWith("open-note");
    expect(onEffect).toHaveBeenCalledTimes(3);
  });

  it("drops unavailable steps instead of crashing", () => {
    const { result } = renderHook(() =>
      useTour(opts({ hasSwitchTarget: false, hasShowcase: false })),
    );
    const keys: string[] = [];
    // walk the whole tour collecting step keys
    while (result.current.active && result.current.step) {
      keys.push(result.current.step.key);
      act(() => result.current.next());
    }
    expect(keys).not.toContain("switch");
    expect(keys).not.toContain("panel");
    expect(keys).toContain("welcome");
  });
});
