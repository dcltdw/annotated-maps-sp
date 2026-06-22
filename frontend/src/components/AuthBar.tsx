import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { login, logout, signup } from "../api/auth";
import type { UserOut } from "../api/types";

interface Props {
  user: UserOut | null;
  onAuthed: (user: UserOut) => void;
  onLoggedOut: () => void;
}

export function AuthBar({ user, onAuthed, onLoggedOut }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [isSignup, setIsSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  if (user) {
    return (
      <div className="authbar">
        <span className="authbar__who">▸ {user.display_name}</span>
        <button type="button" onClick={async () => {
          try {
            await logout();
          } finally {
            onLoggedOut();
          }
        }}>
          {t("auth.logout")}
        </button>
      </div>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(false);
    try {
      const u = isSignup ? await signup(email, password, displayName) : await login(email, password);
      setOpen(false);
      onAuthed(u);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="authbar">
      <button type="button" className="authbar__toggle" onClick={() => setOpen((o) => !o)}>
        {open ? t("auth.close") : t("auth.login")}
      </button>
      {open && (
        <form className="authbar__popover" onSubmit={submit}>
          {isSignup && (
            <label>
              {t("auth.displayName")}
              <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </label>
          )}
          <label>
            {t("auth.email")}
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            {t("auth.password")}
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p className="authbar__error" role="alert">{t("auth.failed")}</p>}
          <button type="submit" disabled={busy}>{isSignup ? t("auth.signup") : t("auth.login")}</button>
          <button type="button" className="authbar__switch" onClick={() => { setIsSignup((s) => !s); setError(false); }}>
            {isSignup ? t("auth.haveAccount") : t("auth.needAccount")}
          </button>
          <p className="authbar__hint">{t("auth.demoHint")}</p>
        </form>
      )}
    </div>
  );
}
