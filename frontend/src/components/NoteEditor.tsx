import { useState } from "react";
import type { Group, NoteEdit, NoteInput, NoteUpdateInput, SectionInput } from "../api/types";
import { SectionEditor } from "./SectionEditor";

const blankSection = (order: number): SectionInput => ({
  order, content: "", rule_type: "public", rule_params: {}, teaser: false, teaser_text: "",
});

interface Props {
  lng: number;
  lat: number;
  groups: Group[];
  authorLabel: string;
  existing?: NoteEdit; // present => edit mode
  onSave: (note: NoteInput | NoteUpdateInput) => void;
  onCancel: () => void;
}

export function NoteEditor({ lng, lat, groups, authorLabel, existing, onSave, onCancel }: Props) {
  const [title, setTitle] = useState(existing?.title ?? "");
  const [sections, setSections] = useState<SectionInput[]>(existing?.sections ?? [blankSection(0)]);
  const [error, setError] = useState<string | null>(null);

  function save() {
    if (!title.trim()) return setError("Title is required.");
    if (sections.length === 0) return setError("Add at least one section.");
    if (sections.some((s) => !s.content.trim())) return setError("Every section needs content.");
    if (sections.some((s) => s.rule_type === "audience" && ((s.rule_params.group_ids as string[]) ?? []).length === 0))
      return setError("Audience sections need at least one group.");
    const ordered = sections.map((s, i) => ({ ...s, order: i }));
    const base: NoteInput = { title: title.trim(), lng, lat, sections: ordered };
    onSave(existing ? { ...base, version: existing.version } : base);
  }

  return (
    <aside className="note-editor">
      <header className="note-editor__head">
        <span>{existing ? "✎ Edit note" : "📝 New note"} · as {authorLabel}</span>
        <button type="button" aria-label="Cancel" onClick={onCancel}>✕</button>
      </header>
      <div className="ed-field">
        <label htmlFor="note-title">Title</label>
        <input
          id="note-title"
          className="ed-input"
          value={title}
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
        ＋ Add section
      </button>
      {error && <p className="ed-error" role="alert">{error}</p>}
      <div className="note-editor__actions">
        <button type="button" className="mock-button" onClick={save}>Save note</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </aside>
  );
}
