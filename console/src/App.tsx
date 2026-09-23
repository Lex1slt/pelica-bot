import { useQuery } from "@tanstack/react-query";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { api, resetGatewayCache } from "./api/client";
import { Skeleton } from "./components/ui";
import { AppLayout } from "./layouts/AppLayout";
import { Dashboard } from "./pages/Dashboard";
import { Flags } from "./pages/Flags";
import { Logs } from "./pages/Logs";
import { Personas } from "./pages/Personas";
import { Profiles } from "./pages/Profiles";
import { Providers } from "./pages/Providers";
import { SandboxPage } from "./pages/Sandbox";
import { Sessions } from "./pages/Sessions";
import { SettingsPage } from "./pages/Settings";
import { System } from "./pages/System";
import { Wizard } from "./pages/Wizard";
import { Corpora } from "./pages/Corpora";

export type Bootstrap = {
  version: string;
  mode: string;
  data_dir: string;
  wizard: { current_step: number; data: Record<string, unknown>; done: boolean };
  character: string;
  core: { running: boolean; pid: number | null; uptime_s: number };
  provider: { kind: string; key_hint: string; has_key: boolean } | null;
  has_corpus: boolean;
  personas: string[];
  groups_count: number;
};

export function useBootstrap() {
  return useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => api<Bootstrap>("/api/bootstrap"),
    // 网关冷启动 10-20s：失败态每 2s 自动重试（重试前清死缓存），成功后停止
    retry: 15,
    retryDelay: 2000,
  });
}

export function App() {
  const boot = useBootstrap();

  if (boot.isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="w-64 space-y-2">
          <p className="text-xs text-ink-muted text-center mb-3">
            正在连接本地网关……
          </p>
          <Skeleton rows={3} />
        </div>
      </div>
    );
  }
  if (boot.isError || !boot.data) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3">
        <p className="text-sm">网关未响应：正在等待本地网关就绪（冷启动约 10-20 秒）……</p>
        <button
          className="text-xs text-accent hover:underline"
          onClick={() => {
            resetGatewayCache();
            void boot.refetch();
          }}
        >
          重新连接
        </button>
      </div>
    );
  }

  if (!boot.data.wizard.done) {
    return <Wizard />;
  }

  return (
    <HashRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/personas" element={<Personas />} />
          <Route path="/corpora" element={<Corpora />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/flags" element={<Flags />} />
          <Route path="/sandbox" element={<SandboxPage />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/system" element={<System />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
