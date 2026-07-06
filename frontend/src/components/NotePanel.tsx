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
  previewAs?: string | null;
  onAppend?: () => void;
  onEditAppend?: (appendId: string) => void;
  onDeleteAppend?: (appendId: string) => void;
  dataTour?: string;
}

export function NotePanel({ note, viewerLabel, onCollapse, canEdit, onEdit, onDelete, previewAs, onAppend, onEditAppend, onDeleteAppend, dataTour }: Props) {
  const { t } = useTranslation();
  return (
    <aside className="note-panel" data-tour={dataTour}>
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
      <div className="appends">
        {note.appends.length > 0 && (
          <div className="appends-label">{t("appends.count", { count: note.appends.length })}</div>
        )}
        {note.appends.map((ap) => {
          // editable is the server's ownership grant; also require a selected persona,
          // since acting as Guest can't write (avoids a dead-click edit affordance).
          const own = ap.editable && previewAs != null;
          return (
            <div className="append" key={ap.id}>
              <div className="append-by">
                <span className="who">{ap.author_name}</span>
                {own && (
                  <span>
                    <button aria-label={t("appends.edit")} onClick={() => onEditAppend?.(ap.id)}>✎</button>
                    <button
                      aria-label={t("appends.delete")}
                      onClick={() => {
                        if (window.confirm(t("appends.deleteConfirm"))) onDeleteAppend?.(ap.id);
                      }}
                    >
                      {t("appends.deleteLabel")}
                    </button>
                  </span>
                )}
              </div>
              {ap.title && <div className="append-title">{ap.title}</div>}
              <SectionList sections={ap.sections} />
            </div>
          );
        })}
        {previewAs != null && (
          <button className="append-btn" onClick={onAppend}>{t("appends.add")}</button>
        )}
      </div>
    </aside>
  );
}
