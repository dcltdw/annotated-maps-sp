import { useTranslation } from "react-i18next";
import type { NoteOut } from "../api/types";
import { colorFor } from "../ruleColors";

interface Props {
  note: NoteOut;
  viewerLabel: string;
  onCollapse: () => void;
}

export function NotePanel({ note, viewerLabel, onCollapse }: Props) {
  const { t } = useTranslation();
  return (
    <aside className="note-panel">
      <header className="note-panel__head">
        <span>📌 {note.title} · {viewerLabel}</span>
        <button aria-label={t("notePanel.collapse")} onClick={onCollapse}>✕</button>
      </header>
      {note.sections.length === 0 ? (
        <p className="note-panel__empty">{t("notePanel.empty", { viewer: viewerLabel })}</p>
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
                <p className="section__locked">{t("notePanel.locked")}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
