import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Group, NoteEdit, NoteInput, NoteUpdateInput, SectionInput, Shape } from "../api/types";
import { SectionEditor } from "./SectionEditor";

const blankSection = (order: number): SectionInput => ({
  order, content: "", rule_type: "public", rule_params: {}, teaser: false, teaser_text: "",
});

interface Props {
  lng: number;
  lat: number;
  shape?: Shape;
  groups: Group[];
  authorLabel: string;
  existing?: NoteEdit; // present => edit mode
  variant?: "note" | "append";
  onSave: (note: NoteInput | NoteUpdateInput) => void;
  onCancel: () => void;
}

export function NoteEditor({ lng, lat, shape, groups, authorLabel, existing, variant = "note", onSave, onCancel }: Props) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(existing?.title ?? "");
  const [sections, setSections] = useState<SectionInput[]>(existing?.sections ?? [blankSection(0)]);
  const [error, setError] = useState<string | null>(null);

  function save() {
    if (variant === "note" && !title.trim()) return setError(t("editor.titleRequired"));
    if (sections.length === 0) return setError(t("editor.oneSection"));
    if (sections.some((s) => !s.content.trim())) return setError(t("editor.contentRequired"));
    if (sections.some((s) => s.rule_type === "audience" && ((s.rule_params.group_ids as string[]) ?? []).length === 0))
      return setError(t("editor.audienceGroup"));
    const ordered = sections.map((s, i) => ({ ...s, order: i }));
    const anchor = shape ? { shape } : { lng, lat };
    const base: NoteInput = { title: title.trim(), ...anchor, sections: ordered };
    onSave(existing ? { ...base, version: existing.version } : base);
  }

  return (
    <aside className="note-editor">
      <header className="note-editor__head">
        <span>{variant === "append"
          ? existing ? t("editor.editAppend") : t("editor.newAppend")
          : existing ? t("editor.editNote") : t("editor.newNote")} · {t("editor.as")} {authorLabel}</span>
        <button type="button" aria-label={t("editor.cancel")} onClick={onCancel}>✕</button>
      </header>
      <div className="ed-field">
        <label htmlFor="note-title">{t("editor.title")}</label>
        <input
          id="note-title"
          className="ed-input"
          value={title}
          placeholder={variant === "append" ? t("editor.titleOptional") : ""}
          onChange={(e) => {
            setTitle(e.target.value);
            setError(null);
          }}
        />
      </div>
      <ul className="note-editor__sections">
        {sections.map((s, i) => (
          <SectionEditor
            key={i}
            section={s}
            groups={groups}
            onChange={(next) => {
              setSections((prev) => prev.map((p, j) => (j === i ? next : p)));
              setError(null);
            }}
            onRemove={() => setSections((prev) => prev.filter((_, j) => j !== i))}
          />
        ))}
      </ul>
      <button type="button" className="ed-add" onClick={() => setSections((p) => [...p, blankSection(p.length)])}>
        {t("editor.addSection")}
      </button>
      {error && <p className="ed-error" role="alert">{error}</p>}
      <div className="note-editor__actions">
        <button type="button" className="mock-button" onClick={save}>
          {variant === "append" ? t("editor.saveAppend") : t("editor.save")}
        </button>
        <button type="button" onClick={onCancel}>{t("editor.cancel")}</button>
      </div>
    </aside>
  );
}
