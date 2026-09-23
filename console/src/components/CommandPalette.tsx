/** CommandPalette（Ctrl+K）：搜索群/人设/开关/动作。 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CornerDownLeft, Search } from "lucide-react";
import { useUI } from "../store/ui";

type Item = { id: string; label: string; group: string; run: () => void };

export function CommandPalette() {
  const { paletteOpen, setPaletteOpen } = useUI();
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const items = useMemo<Item[]>(() => {
    const base: Item[] = [
      { id: "nav-dash", label: "打开仪表盘", group: "导航", run: () => navigate("/") },
      { id: "nav-sandbox", label: "打开测试沙箱", group: "导航", run: () => navigate("/sandbox") },
      { id: "nav-profiles", label: "打开方案中心", group: "导航", run: () => navigate("/profiles") },
      { id: "nav-personas", label: "打开人设管理", group: "导航", run: () => navigate("/personas") },
      { id: "nav-corpus", label: "打开语料库", group: "导航", run: () => navigate("/corpora") },
      { id: "nav-sessions", label: "打开会话与白名单", group: "导航", run: () => navigate("/sessions") },
      { id: "nav-providers", label: "打开模型与 API", group: "导航", run: () => navigate("/providers") },
      { id: "nav-flags", label: "打开功能开关", group: "导航", run: () => navigate("/flags") },
      { id: "nav-logs", label: "打开日志与审计", group: "导航", run: () => navigate("/logs") },
      { id: "nav-system", label: "打开备份与诊断", group: "导航", run: () => navigate("/system") },
      { id: "nav-settings", label: "打开设置", group: "导航", run: () => navigate("/settings") },
      { id: "act-simple", label: "切换到简单模式", group: "动作", run: () => useUI.getState().setMode("simple") },
      { id: "act-advanced", label: "切换到高级模式", group: "动作", run: () => useUI.getState().setMode("advanced") },
      {
        id: "act-theme",
        label: "切换亮色/暗色主题",
        group: "动作",
        run: () => useUI.getState().toggleTheme(),
      },
    ];
    return base;
  }, [navigate]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => it.label.toLowerCase().includes(q));
  }, [items, query]);

  useEffect(() => {
    if (paletteOpen) {
      setQuery("");
      setCursor(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [paletteOpen]);

  if (!paletteOpen) return null;

  const commit = (item?: Item) => {
    const target = item ?? filtered[cursor];
    if (!target) return;
    target.run();
    setPaletteOpen(false);
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center pt-[15vh]"
      onClick={() => setPaletteOpen(false)}
      role="presentation"
    >
      <div
        className="w-[480px] bg-surface border border-line rounded-[14px] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="命令面板"
      >
        <div className="flex items-center gap-2 px-3.5 h-11 border-b border-line">
          <Search size={15} className="text-ink-muted" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            placeholder="搜索群、人设、开关、动作…"
            className="flex-1 bg-transparent outline-none text-[13px] placeholder:text-ink-muted/60"
            onChange={(e) => {
              setQuery(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, filtered.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter") {
                commit();
              } else if (e.key === "Escape") {
                setPaletteOpen(false);
              }
            }}
          />
          <kbd className="text-[10px] text-ink-muted border border-line rounded px-1">Esc</kbd>
        </div>
        <ul className="max-h-[300px] overflow-y-auto py-1.5">
          {filtered.length === 0 && (
            <li className="px-4 py-3 text-xs text-ink-muted">没有匹配项。</li>
          )}
          {filtered.map((it, i) => (
            <li key={it.id}>
              <button
                className={`w-full flex items-center gap-2 px-4 h-8 text-left text-[13px] ${
                  i === cursor ? "bg-accent/12 text-accent" : "hover:bg-elevated"
                }`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => commit(it)}
              >
                <span className="text-[10px] text-ink-muted w-8 shrink-0">
                  {it.group}
                </span>
                <span className="flex-1">{it.label}</span>
                {i === cursor && (
                  <CornerDownLeft size={12} className="text-ink-muted" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
