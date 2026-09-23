/** UI 本地状态（zustand）：主题 / 模式 / 侧栏 / 命令面板 / Toast。 */

import { create } from "zustand";

export type Theme = "dark" | "light";
export type UIMode = "simple" | "advanced";

export type Toast = {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

type UIState = {
  theme: Theme;
  mode: UIMode;
  paletteOpen: boolean;
  sidebarCollapsed: boolean;
  toasts: Toast[];
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setMode: (m: UIMode) => void;
  setPaletteOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  toast: (t: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
};

function initialTheme(): Theme {
  const saved = localStorage.getItem("pelica.theme");
  if (saved === "dark" || saved === "light") return saved;
  return "dark";
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("pelica.theme", theme);
}

applyTheme(initialTheme());

let nextToastId = 1;

export const useUI = create<UIState>((set, get) => ({
  theme: initialTheme(),
  mode: (localStorage.getItem("pelica.mode") as UIMode) || "simple",
  paletteOpen: false,
  sidebarCollapsed: false,
  toasts: [],
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
  setMode: (mode) => {
    localStorage.setItem("pelica.mode", mode);
    set({ mode });
  },
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
  toast: (t) => {
    const id = nextToastId++;
    set({ toasts: [...get().toasts, { ...t, id }] });
    setTimeout(() => get().dismissToast(id), 5000);
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));
