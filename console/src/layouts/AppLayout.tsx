/** 侧栏 + 顶栏布局：简单模式视图过滤、Ctrl+K 面板、Ctrl+Shift+S 快速沙箱、托盘三态同步。 */

import { useEffect, useRef } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Bot,
  Boxes,
  ClipboardList,
  FlaskConical,
  Gauge,
  KeyRound,
  LayoutGrid,
  MessageSquareLock,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Settings,
  Sun,
  TestTubes,
} from "lucide-react";
import { useBootstrap } from "../App";
import { useCoreStatus } from "../api/hooks";
import { shellInvoke } from "../api/client";
import { StatusDot } from "../components/ui";
import { CommandPalette } from "../components/CommandPalette";
import { useUI } from "../store/ui";

const NAV = [
  { to: "/", label: "仪表盘", icon: Gauge, simple: true },
  { to: "/profiles", label: "方案中心", icon: Boxes, simple: true },
  { to: "/personas", label: "人设", icon: Bot, simple: false },
  { to: "/corpora", label: "语料库", icon: ClipboardList, simple: false },
  { to: "/sessions", label: "会话与白名单", icon: MessageSquareLock, simple: true },
  { to: "/providers", label: "模型与 API", icon: KeyRound, simple: false },
  { to: "/flags", label: "功能开关", icon: LayoutGrid, simple: false },
  { to: "/sandbox", label: "测试沙箱", icon: FlaskConical, simple: true },
  { to: "/logs", label: "日志与审计", icon: ScrollText, simple: true },
  { to: "/system", label: "备份与诊断", icon: TestTubes, simple: false },
  { to: "/settings", label: "设置", icon: Settings, simple: false },
];

export function AppLayout() {
  const { mode, theme, setPaletteOpen, toggleTheme, sidebarCollapsed, toggleSidebar } =
    useUI();
  const boot = useBootstrap();
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        navigate("/sandbox");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen, navigate]);

  const items = NAV.filter((n) => mode === "advanced" || n.simple);
  const status = useCoreStatus();
  const running = status.data?.core.running ?? boot.data?.core.running ?? false;
  const bridgeDetail = status.data?.bridge;

  // 托盘三态同步（Tauri 环境）：running / silent / offline
  const failStreak = useRef(0);
  const lastTrayMode = useRef("");
  useEffect(() => {
    if (status.data) failStreak.current = 0;
    else if (status.isError) failStreak.current += 1;
    const trayMode =
      status.data
        ? running
          ? "running"
          : "silent"
        : failStreak.current >= 3
          ? "offline"
          : "";
    if (trayMode && trayMode !== lastTrayMode.current) {
      lastTrayMode.current = trayMode;
      void shellInvoke("set_tray", { mode: trayMode });
    }
  }, [status.data, status.isError, running]);

  return (
    <div className="h-full flex">
      <aside
        className={`flex flex-col border-r border-line bg-surface transition-[width] duration-[180ms] ${
          sidebarCollapsed ? "w-14" : "w-52"
        }`}
      >
        <div className="h-12 flex items-center gap-2 px-3 border-b border-line">
          <span
            className="w-6 h-6 rounded-[6px] bg-accent/15 border border-accent/40 flex items-center justify-center text-[13px]"
            aria-hidden
          >
            🦉
          </span>
          {!sidebarCollapsed && (
            <div className="leading-tight">
              <p className="text-[13px] font-semibold">Pelica Console</p>
              <p className="text-[10px] text-ink-muted">
                v{boot.data?.version ?? "…"}
              </p>
            </div>
          )}
        </div>
        <nav className="flex-1 py-2 space-y-0.5 overflow-y-auto">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={label}
              className={({ isActive }) =>
                `flex items-center gap-2.5 mx-1.5 px-2.5 h-8 rounded-[6px] text-[13px] transition-colors ${
                  isActive
                    ? "bg-accent/12 text-accent"
                    : "text-ink-muted hover:text-ink hover:bg-elevated"
                }`
              }
            >
              <Icon size={15} aria-hidden />
              {!sidebarCollapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-line flex items-center gap-1">
          <button
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
            className="p-1.5 rounded text-ink-muted hover:text-ink hover:bg-elevated"
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={15} />
            ) : (
              <PanelLeftClose size={15} />
            )}
          </button>
          <button
            onClick={toggleTheme}
            aria-label="切换主题"
            className="p-1.5 rounded text-ink-muted hover:text-ink hover:bg-elevated"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          {!sidebarCollapsed && (
            <span className="ml-auto text-[10px] text-ink-muted mono">
              Ctrl+K
            </span>
          )}
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-12 flex items-center gap-3 px-5 border-b border-line bg-surface/60 backdrop-blur">
          <StatusDot status={running ? "running" : "off"} />
          <p className="text-xs text-ink-muted">
            {running
              ? `机器人运行中 · ${boot.data?.character ?? ""} · ${
                  bridgeDetail?.mode === "mock"
                    ? "沙箱模式"
                    : bridgeDetail?.connected
                      ? "微信已连接"
                      : "微信未连上"
                }`
              : "机器人未运行 · 可在仪表盘启动"}
          </p>
          <div className="flex-1" />
          <button
            onClick={() => setPaletteOpen(true)}
            className="text-xs text-ink-muted hover:text-ink border border-line rounded-[6px] px-2.5 h-7 flex items-center gap-1.5 hover:border-line-strong"
          >
            搜索一切…
          </button>
        </header>
        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
