import { useEffect, useState } from "react";
import { fieldClass } from "./ui";

type Theme = "system" | "light" | "dark";
const key = "pf_theme";
let unsavedPreference: Theme | undefined;
function preference(): Theme {
  if (unsavedPreference !== undefined) return unsavedPreference;
  try { const value = localStorage.getItem(key); return value === "light" || value === "dark" ? value : "system"; }
  catch { return "system"; }
}
export function applyTheme(theme = preference()) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#14171c" : "#f5f6f8");
}
export function ThemeSync() {
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const sync = () => applyTheme();
    const syncStorage = (event: StorageEvent) => {
      if (event.key !== key && event.key !== null) return;
      unsavedPreference = undefined;
      sync();
    };
    media?.addEventListener("change", sync);
    window.addEventListener("storage", syncStorage);
    return () => { media?.removeEventListener("change", sync); window.removeEventListener("storage", syncStorage); };
  }, []);
  return null;
}
export function ThemeControl({compact = false}: {compact?: boolean} = {}) {
  const [theme, setTheme] = useState<Theme>(preference);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === key || event.key === null) {
        unsavedPreference = undefined;
        setTheme(preference());
      }
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  useEffect(() => {
    applyTheme(theme);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme);
    media?.addEventListener("change", update);
    return () => media?.removeEventListener("change", update);
  }, [theme]);
  return <label className="block text-sm font-medium"><span className={compact ? "sr-only" : undefined}>Appearance</span>
    <select className={`${fieldClass} ${compact ? "" : "mt-2"}`} value={theme} onChange={event => {
      const value = event.target.value as Theme;
      try { localStorage.setItem(key, value); unsavedPreference = undefined; }
      catch { unsavedPreference = value; }
      setTheme(value);
    }}>
      <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
  </label>;
}
