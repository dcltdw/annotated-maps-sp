import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TOUR_SEEN_KEY, TOUR_STEPS, type TourStep } from "./tourSteps";

interface UseTourOptions {
  /** map + notes loaded successfully (never auto-start over the waking screen) */
  ready: boolean;
  loggedOut: boolean;
  /** the Running Friend viewer is present in the viewers list */
  hasSwitchTarget: boolean;
  /** the showcase note is present in the loaded notes */
  hasShowcase: boolean;
  onEffect: (effect: NonNullable<TourStep["effect"]>) => void;
}

export function useTour({ ready, loggedOut, hasSwitchTarget, hasShowcase, onEffect }: UseTourOptions) {
  const [index, setIndex] = useState<number | null>(null);

  // Availability filtering: degrade by dropping steps, never by crashing (spec §2).
  const steps = useMemo(
    () =>
      TOUR_STEPS.filter((s) => {
        if (s.key === "switch") return hasSwitchTarget;
        if (s.key === "panel") return hasShowcase;
        return true;
      }),
    [hasSwitchTarget, hasShowcase],
  );

  // Auto-start once. State-based gate (localStorage), not call counts — StrictMode
  // double-invokes effects in dev and both invocations see the same store.
  useEffect(() => {
    if (!ready || !loggedOut) return;
    if (localStorage.getItem(TOUR_SEEN_KEY) !== null) return;
    localStorage.setItem(TOUR_SEEN_KEY, String(Date.now()));
    setIndex(0);
  }, [ready, loggedOut]);

  // Fire a step's side effect exactly once per entry.
  const firedFor = useRef<number | null>(null);
  useEffect(() => {
    if (index === null || firedFor.current === index) return;
    firedFor.current = index;
    const effect = steps[index]?.effect;
    if (effect) onEffect(effect);
  }, [index, steps, onEffect]);

  const start = useCallback(() => {
    localStorage.setItem(TOUR_SEEN_KEY, String(Date.now()));
    firedFor.current = null;
    setIndex(0);
  }, []);
  const close = useCallback(() => {
    firedFor.current = null;
    setIndex(null);
  }, []);
  const next = useCallback(
    () => setIndex((i) => (i === null ? null : i + 1 >= steps.length ? null : i + 1)),
    [steps.length],
  );
  const back = useCallback(() => setIndex((i) => (i === null || i === 0 ? i : i - 1)), []);

  return {
    active: index !== null,
    step: index === null ? null : (steps[index] ?? null),
    index: index ?? 0,
    total: steps.length,
    start,
    next,
    back,
    skip: close,
  };
}
