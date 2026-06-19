import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { modRecent, modDelete, type ModItem, type ModDeleteBody } from "./api/mod";

export function ModerationScreen() {
  const { t } = useTranslation();
  const [token, setToken] = useState<string>(() => sessionStorage.getItem("modToken") ?? "");
  const [entry, setEntry] = useState("");
  const [items, setItems] = useState<ModItem[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (tok: string) => {
      try {
        setItems(await modRecent(tok));
        setError(null);
      } catch (e) {
        if (String(e).includes("401")) {
          setToken("");
          sessionStorage.removeItem("modToken");
          setError(t("mod.badToken"));
        } else {
          setError(t("mod.loadFailed"));
        }
      }
    },
    [t],
  );

  useEffect(() => {
    if (token) load(token);
  }, [token, load]);

  const run = async (body: ModDeleteBody, confirmMsg: string) => {
    if (!window.confirm(confirmMsg)) return;
    try {
      await modDelete(token, body);
      setChecked(new Set());
      await load(token);
    } catch {
      setError(t("mod.deleteFailed"));
    }
  };

  if (!token) {
    return (
      <main className="mod-screen">
        <h1>{t("mod.title")}</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem("modToken", entry);
            setToken(entry);
          }}
        >
          <input
            type="password"
            aria-label={t("mod.tokenLabel")}
            placeholder={t("mod.tokenLabel")}
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
          />
          <button type="submit">{t("mod.unlock")}</button>
        </form>
        {error && <p className="mod-error">{error}</p>}
      </main>
    );
  }

  return (
    <main className="mod-screen">
      <h1>{t("mod.title")}</h1>
      {error && <p className="mod-error">{error}</p>}
      <button
        disabled={checked.size === 0}
        onClick={() => run({ ids: [...checked] }, t("mod.confirmSelected", { count: checked.size }))}
      >
        {t("mod.deleteSelected", { count: checked.size })}
      </button>
      <table className="mod-table">
        <thead>
          <tr>
            <th></th>
            <th>{t("mod.kind")}</th>
            <th>{t("mod.title")}</th>
            <th>{t("mod.author")}</th>
            <th>{t("mod.session")}</th>
            <th>{t("mod.ip")}</th>
            <th>{t("mod.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.id}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`select ${it.id}`}
                  checked={checked.has(it.id)}
                  onChange={(e) => {
                    const next = new Set(checked);
                    if (e.target.checked) next.add(it.id);
                    else next.delete(it.id);
                    setChecked(next);
                  }}
                />
              </td>
              <td>{it.kind}</td>
              <td>{it.title || it.snippet}</td>
              <td>{it.author_name}</td>
              <td title={it.session_key}>{it.session_key.slice(0, 8)}</td>
              <td>{it.created_ip}</td>
              <td>
                <button onClick={() => run({ session_key: it.session_key }, t("mod.confirmSession"))}>
                  {t("mod.delSession")}
                </button>
                {it.created_ip && (
                  <button onClick={() => run({ created_ip: it.created_ip! }, t("mod.confirmIp"))}>
                    {t("mod.delIp")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
