// @ts-strict-ignore
import { createContext, useEffect, useState } from "react";

type darkContextType = {
  dark: {};
  setDark: (newState: {}) => void;
};

const initialValue = {
  dark: {},
  setDark: () => { },
};

export const darkContext = createContext<darkContextType>(initialValue);

export function DarkProvider({ children }) {
  const [dark, setDark] = useState(
    JSON.parse(window.localStorage.getItem("isDark")) ?? false
  );
  useEffect(() => {
    // `.dark` goes on BOTH <html> and <body>; each one fixes a different layer.
    //
    // <html>: the shared tokens (@bisheng/ui tokens.css) declare semantic
    // aliases such as `--text-1: var(--arco-gray-10)` on :root, and var()
    // inside a custom property is resolved on the element that declares it.
    // With `.dark` only on <body> those aliases were frozen at their light
    // values — 35 tokens (text-1/3/4, fill-*, border-*, …) never flipped,
    // while literal ones like `--warning-tint` did: dark tint, near-black
    // text. platformThemeBridge also reads `.dark` from <html>.
    //
    // <body>: index.html writes the saved admin theme — a LIGHT-only legacy
    // palette (--background, --card, --muted, …) — as inline styles on
    // <html>, and inline beats a `.dark` rule on that same element. The
    // legacy `.dark` palette only wins one level down, so it has to stay on
    // <body> or the page background and cards turn white in dark mode.
    const isDark = Boolean(dark);
    document.documentElement.classList.toggle("dark", isDark);
    document.body.classList.toggle("dark", isDark);
    window.localStorage.setItem("isDark", dark.toString());
  }, [dark]);
  return (
    <darkContext.Provider
      value={{
        dark,
        setDark,
      }}
    >
      {children}
    </darkContext.Provider>
  );
}
