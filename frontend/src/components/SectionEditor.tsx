import { useTranslation } from "react-i18next";
import type { Group, SectionInput } from "../api/types";
import { colorFor } from "../ruleColors";

const RULES = ["public", "audience", "attribute_gate", "private"] as const;
const LABEL: Record<(typeof RULES)[number], string> = {
  public: "Public",
  audience: "Audience",
  attribute_gate: "Reputation ≥ N",
  private: "Private",
};

interface Props {
  section: SectionInput;
  groups: Group[];
  onChange: (next: SectionInput) => void;
  onRemove: () => void;
}

// Purely controlled: renders straight from `section` and emits every change via
// onChange. The parent (NoteEditor) owns the sections array — single source of truth.
export function SectionEditor({ section, groups, onChange, onRemove }: Props) {
  const { t } = useTranslation();
  const set = (patch: Partial<SectionInput>) => onChange({ ...section, ...patch });

  function pickRule(rule: string) {
    // reset rule_params + teaser to sensible defaults for the new rule
    const params =
      rule === "attribute_gate"
        ? { attribute: "reputation", threshold: 50 }
        : rule === "audience"
          ? { group_ids: [] }
          : {};
    set({ rule_type: rule, rule_params: params, teaser: rule === "public" ? false : section.teaser });
  }

  const groupIds = (section.rule_params.group_ids as string[] | undefined) ?? [];
  function toggleGroup(id: string) {
    const next = groupIds.includes(id) ? groupIds.filter((g) => g !== id) : [...groupIds, id];
    set({ rule_params: { ...section.rule_params, group_ids: next } });
  }

  return (
    <li className="ed-section" style={{ borderLeftColor: colorFor(section.rule_type) }}>
      <div className="ed-section__rules" role="group" aria-label="Section visibility">
        {RULES.map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={section.rule_type === r}
            style={section.rule_type === r ? { background: colorFor(r), color: "#fff" } : undefined}
            onClick={() => pickRule(r)}
          >
            {LABEL[r]}
          </button>
        ))}
        <button type="button" className="ed-section__remove" aria-label={t("editor.removeSection")} onClick={onRemove}>
          ✕
        </button>
      </div>

      {section.rule_type === "audience" && (
        <div className="ed-groups">
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              aria-pressed={groupIds.includes(g.id)}
              onClick={() => toggleGroup(g.id)}
            >
              {g.name}
            </button>
          ))}
        </div>
      )}

      {section.rule_type === "attribute_gate" && (
        <label className="ed-threshold">
          Reputation ≥{" "}
          <input
            type="number"
            value={Number(section.rule_params.threshold ?? 50)}
            onChange={(e) =>
              set({
                rule_params: {
                  ...section.rule_params,
                  attribute: "reputation",
                  threshold: Number(e.target.value),
                },
              })
            }
          />
        </label>
      )}

      <textarea
        className="ed-input"
        aria-label={t("editor.sectionContent")}
        value={section.content}
        onChange={(e) => set({ content: e.target.value })}
      />

      {section.rule_type !== "public" && (
        <label className="ed-teaser">
          {t("editor.teaser")}
          <input
            type="text"
            value={section.teaser_text}
            placeholder="optional hook — default: hidden entirely"
            onChange={(e) => set({ teaser_text: e.target.value, teaser: e.target.value.length > 0 })}
          />
        </label>
      )}
    </li>
  );
}
