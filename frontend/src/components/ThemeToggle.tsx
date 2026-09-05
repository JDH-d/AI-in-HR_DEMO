import { Moon, Sun } from "@phosphor-icons/react";
import { useTheme } from "../app/theme";
import { Hint } from "./ui";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const label = `Switch to ${theme === "dark" ? "light" : "dark"} theme`;
  return (
    <Hint label={label}>
      <button type="button" className="icon-button" aria-label={label} onClick={toggleTheme}>
        {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
      </button>
    </Hint>
  );
}
