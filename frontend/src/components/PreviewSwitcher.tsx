import type { Viewer } from "../api/types";

interface Props {
  viewers: Viewer[];
  current: string | null;
  onChange: (id: string | null) => void;
}

export function PreviewSwitcher({ viewers, current, onChange }: Props) {
  return (
    <div className="switcher" role="group" aria-labelledby="switcher-label">
      <span id="switcher-label" className="switcher__label">
        Viewing as
      </span>
      <button aria-pressed={current === null} onClick={() => onChange(null)}>Guest</button>
      {viewers.map((v) => (
        <button key={v.id} aria-pressed={current === v.id} onClick={() => onChange(v.id)}>
          {v.display_name}
        </button>
      ))}
    </div>
  );
}
