import { useTranslation } from "react-i18next";
import type { NoteOut } from "../api/types";
import { SectionList } from "./SectionList";

interface Props {
  note: NoteOut;
  viewerLabel: string;
  onCollapse: () => void;
  canEdit?: boolean;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function NotePanel({ note, viewerLabel, onCollapse, canEdit, onEdit, onDelete }: Props) {
  const { t } = useTranslation();
  return (
    <aside className="note-panel">
      <header className="note-panel__head">
        <span>📌 {note.title} · {viewerLabel}</span>
        <div className="note-panel__head-actions">
          {canEdit && (
            <>
              <button aria-label={t("notePanel.edit")} onClick={onEdit}>✎</button>
              <button
                aria-label={t("notePanel.delete")}
                onClick={() => {
                  if (window.confirm(t("notePanel.deleteConfirm"))) onDelete?.();
                }}
              >
                {t("notePanel.deleteLabel")}
              </button>
            </>
          )}
          <button aria-label={t("notePanel.collapse")} onClick={onCollapse}>✕</button>
        </div>
      </header>
      {note.sections.length === 0 ? (
        <p className="note-panel__empty">{t("notePanel.empty", { viewer: viewerLabel })}</p>
      ) : (
        <SectionList sections={note.sections} />
      )}
    </aside>
  );
}
