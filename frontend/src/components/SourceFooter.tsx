import { useTranslation } from "react-i18next";

import { LICENSE_SPDX, REPO_URL } from "../lib/repo";

/**
 * Persistent source offer, required by AGPL-3.0 section 13: users who only ever
 * interact with the deployed service still have to be offered the Corresponding
 * Source. The About popover also links the repo, but that offer is only visible
 * after a click -- this one is always on screen, which is what "prominently
 * offer" asks for.
 */
export function SourceFooter() {
  const { t } = useTranslation();
  return (
    <footer className="source-footer">
      <span className="source-footer__license">
        {t("footer.license", { license: LICENSE_SPDX })}
      </span>
      <a
        className="source-footer__link"
        href={REPO_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t("footer.source")}
      </a>
    </footer>
  );
}
