import type { NoteOut } from "../api/types";
import { colorFor } from "../ruleColors";

interface Props {
  note: NoteOut;
  viewerLabel: string;
  onCollapse: () => void;
}

export function NotePanel({ note, viewerLabel, onCollapse }: Props) {
  return (
    <aside className="note-panel">
      <header className="note-panel__head">
        <span>📌 {note.title} · {viewerLabel}</span>
        <button aria-label="Collapse panel" onClick={onCollapse}>✕</button>
      </header>
      {note.sections.length === 0 ? (
        <p className="note-panel__empty">Nothing here for {viewerLabel}.</p>
      ) : (
        <ul className="note-panel__sections">
          {note.sections.map((s) => (
            <li key={s.id} className="section" style={{ borderLeftColor: colorFor(s.rule_type) }}>
              <span className="section__chip" style={{ color: colorFor(s.rule_type) }}>
                {s.visibility === "teaser" ? `🔒 ${s.rule_label}` : s.rule_label}
              </span>
              {s.visibility === "visible" ? (
                s.content ? <p>{s.content}</p> : null
              ) : (
                <p className="section__locked">Locked — join to unlock.</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
