import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TourStep } from "./tourSteps";

interface Props {
  step: TourStep;
  index: number;
  total: number;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PAD = 8; // px of breathing room around the spotlit element

export function TourOverlay({ step, index, total, onNext, onBack, onSkip }: Props) {
  const { t } = useTranslation();
  const [rect, setRect] = useState<Rect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Measure the target on step change and window resize. The initial call is
  // synchronous so an already-mounted target spotlights immediately; the rAF
  // pass re-measures after paint, letting a step's side effect (e.g. opening
  // the NotePanel) render before we check for its target.
  useEffect(() => {
    const measure = () => {
      const el = step.target
        ? document.querySelector(`[data-tour="${step.target}"]`)
        : null;
      if (!el) {
        setRect(null);
        return;
      }
      const r = el.getBoundingClientRect();
      setRect({
        top: r.top - PAD,
        left: r.left - PAD,
        width: r.width + PAD * 2,
        height: r.height + PAD * 2,
      });
    };
    measure();
    const raf = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      cancelAnimationFrame(raf);
    };
  }, [step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onSkip();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onSkip]);

  // Focus management (spec §4): focus the card on step change, trap Tab within it,
  // and restore focus to whatever had it when the tour closes.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    return () => previouslyFocused?.focus();
  }, []);
  useEffect(() => {
    cardRef.current?.focus();
  }, [step]);
  const trapTab = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !cardRef.current) return;
    const focusables = cardRef.current.querySelectorAll<HTMLElement>("button");
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const isLast = index === total - 1;
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={t("tour.aria")}>
      {rect ? (
        // One element: the spotlight hole; the giant box-shadow is the dim layer.
        <div
          className="tour-spotlight"
          style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
        />
      ) : (
        <div className="tour-dim" />
      )}
      {/* click-shield backdrop, not a semantic control: it's a click-to-dismiss
          area for mouse users, so it's aria-hidden and inert; Escape and the
          visible Skip button already cover keyboard/AT users. */}
      <div className="tour-shield" onClick={onSkip} aria-hidden="true" />
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions --
          focus-trap container: onKeyDown here only intercepts Tab to cycle
          focus among the buttons inside, it's not a mouse-activated control,
          and the dialog semantics already live on the outer .tour element. */}
      <div className={`tour-card${step.target ? "" : " tour-card--center"}`} ref={cardRef} tabIndex={-1} onKeyDown={trapTab}>
        <p className="tour-card__body">{t(step.copyKey)}</p>
        <div className="tour-card__row">
          <span className="tour-card__progress">{`${index + 1} / ${total}`}</span>
          <span className="tour-card__buttons">
            <button type="button" onClick={onSkip}>{t("tour.skip")}</button>
            {index > 0 && (
              <button type="button" onClick={onBack}>{t("tour.back")}</button>
            )}
            <button type="button" className="tour-card__next" onClick={onNext}>
              {t(isLast ? "tour.done" : "tour.next")}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
