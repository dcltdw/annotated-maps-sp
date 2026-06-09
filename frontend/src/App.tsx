import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import "./i18n";
import { fetchHealth } from "./api/health";

export default function App() {
  const { t } = useTranslation();
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    fetchHealth().then(() => setOk(true)).catch(() => setOk(false));
  }, []);
  return (
    <main>
      <h1>{t("health.title")}</h1>
      <p role="status">{ok === null ? "…" : ok ? t("health.ok") : t("health.error")}</p>
    </main>
  );
}
