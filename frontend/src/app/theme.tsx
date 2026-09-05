import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const storageKey = "peopleflow.theme";
const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

function savedTheme(): Theme {
  try {
    return localStorage.getItem(storageKey) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#10161e" : "#f6f6f3");
    try {
      localStorage.setItem(storageKey, theme);
    } catch {
      /* The theme still works when storage is unavailable. */
    }
  }, [theme]);
  return (
    <ThemeContext.Provider
      value={{
        theme,
        toggleTheme: () => setTheme((current) => (current === "dark" ? "light" : "dark")),
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("Theme provider missing");
  return context;
}
