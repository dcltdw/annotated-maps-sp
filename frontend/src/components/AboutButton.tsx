import { useState } from "react";
import { useTranslation } from "react-i18next";

const REPO_URL = "https://github.com/dcltdw/annotated-maps-sp";

/** Small "About" popover in the topbar: who built it + a link to the source repo. */
export function AboutButton() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className="about">
      <button
        type="button"
        className="about__toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {t("about.label")}
      </button>
      {open && (
        <div className="about__popover" role="dialog" aria-label={t("about.label")}>
          <p className="about__heading">{t("app.title")}</p>
          <p className="about__desc">{t("about.desc")}</p>
          <p className="about__by">{t("about.by")}</p>
          <a className="about__link" href={REPO_URL} target="_blank" rel="noopener noreferrer">
            {t("about.source")}
          </a>
        </div>
      )}
    </div>
  );
}
