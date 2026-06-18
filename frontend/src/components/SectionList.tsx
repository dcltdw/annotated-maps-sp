import { useTranslation } from "react-i18next";
import type { SectionOut } from "../api/types";
import { colorFor } from "../ruleColors";

export function SectionList({ sections }: { sections: SectionOut[] }) {
  const { t } = useTranslation();
  return (
    <ul className="note-panel__sections">
      {sections.map((s) => (
        <li key={s.id} className="section" style={{ borderLeftColor: colorFor(s.rule_type) }}>
          <span className="section__chip" style={{ color: colorFor(s.rule_type) }}>
            {s.visibility === "teaser" ? `🔒 ${s.rule_label}` : s.rule_label}
          </span>
          {s.visibility === "visible" ? (
            s.content ? <p>{s.content}</p> : null
          ) : (
            <p className="section__locked">{s.teaser_text ?? t("notePanel.locked")}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
