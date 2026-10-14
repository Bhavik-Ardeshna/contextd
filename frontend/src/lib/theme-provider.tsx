import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light" | "system";

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
};

type ThemeProviderState = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  resolvedTheme: "dark" | "light";
};

const initialState: ThemeProviderState = {
  theme: "system",
  setTheme: () => null,
  resolvedTheme: "light",
};

const ThemeProviderContext = createContext<ThemeProviderState>(initialState);
const DEFAULT_THEME_STORAGE_KEY = "contextd-ui-theme";

const readStoredTheme = (storageKey: string, defaultTheme: Theme): Theme => {
  const storedTheme = localStorage.getItem(storageKey) as Theme | null;
  if (storedTheme) return storedTheme;

  return defaultTheme;
};

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = DEFAULT_THEME_STORAGE_KEY,
  ...props
}: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(
    () => readStoredTheme(storageKey, defaultTheme)
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  );

  useEffect(() => {
    const root = window.document.documentElement;

    root.classList.remove("light", "dark");

    if (theme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)")
        .matches
        ? "dark"
        : "light";

      root.classList.add(systemTheme);
      setResolvedTheme(systemTheme);
      return;
    }

    root.classList.add(theme);
    setResolvedTheme(theme);
  }, [theme]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    // Define the handler function
    const handleChange = () => {
      if (theme === "system") {
        const root = window.document.documentElement;
        root.classList.remove("light", "dark");

        const systemTheme = mediaQuery.matches ? "dark" : "light";
        root.classList.add(systemTheme);
        setResolvedTheme(systemTheme);
      }
    };

    // Add the event listener
    mediaQuery.addEventListener("change", handleChange);

    // Clean up the event listener when the component unmounts
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, [theme]);

  const value = {
    theme,
    resolvedTheme,
    setTheme: (theme: Theme) => {
      localStorage.setItem(storageKey, theme);
      setTheme(theme);
    },
  };

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext);

  if (context === undefined)
    throw new Error("useTheme must be used within a ThemeProvider");

  return context;
};
