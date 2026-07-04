// Structure lives here; copy lives ONLY in en.json (tour.*). See the demo-tour spec.

// Cross-layer contracts — asserted by backend/maps/tests/test_tour_contract.py.
// Changing either string means the seed data must change in the same PR.
export const SHOWCASE_TITLE = "Charles River loop";
export const TOUR_PERSONA_NAME = "A Running Friend";

export const TOUR_SEEN_KEY = "tourSeenV1"; // bump the suffix to re-show a revamped tour

export interface TourStep {
  key: string;
  /** data-tour attribute of the spotlight target; null = centered card, full dim */
  target: "map" | "switcher" | "panel" | "authbar" | null;
  copyKey: string;
  effect?: "reset-persona" | "switch-persona" | "open-note";
}

export const TOUR_STEPS: TourStep[] = [
  { key: "welcome", target: null, copyKey: "tour.welcome" },
  { key: "map", target: "map", copyKey: "tour.map", effect: "reset-persona" },
  { key: "switcher", target: "switcher", copyKey: "tour.switcher" },
  { key: "switch", target: "map", copyKey: "tour.switch", effect: "switch-persona" },
  { key: "panel", target: "panel", copyKey: "tour.panel", effect: "open-note" },
  { key: "authbar", target: "authbar", copyKey: "tour.authbar" },
];
