/** 设置：外观/模式/数据目录/桥接/调度 + .env 导出（密钥占位）。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApiQuery } from "../api/hooks";
import { useBootstrap } from "../App";
import { Badge, Button, Card, Field, Input, Select, Skeleton } from "../components/ui";
import { useUI } from "../store/ui";

export function SettingsPage() {
  const boot = useBootstrap();
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const { mode, setMode, theme, setTheme } = useUI();
  const settings = useApiQuery<Record<string, unknown>>(["settings"], "/api/settings");
  const [bridge, setBridge] = useState(String(settings.data?.["bridge.mode"] ?? "mock"));
  const [tz, setTz] = useState(String(settings.data?.["schedule.timezone"] ?? "Asia/Shanghai"));

  const save = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api("/api/settings", { method: "PUT", body: JSON.stringify({ values }) }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "已保存。" });
    },
    onError: (e) => toast({ kind: "error", message: String(e) }),
  });

  const exportEnv = useMutation({
    mutationFn: async () => {
      const eff = (await api<Record<string, unknown>>("/api/settings")) ?? {};
      const lines = [
        "# 由 Pelica Console 导出（密钥以占位符代替，请重新填写）",
        "DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx",
        `BRIDGE_MODE=${String(eff["bridge.mode"] ?? "mock")}`,
        `CHARACTER=${String(eff["character.active"] ?? "pelica")}`,
        `TIMEZONE=${String(eff["schedule.timezone"] ?? "Asia/Shanghai")}`,
        `GROUP_WHITELIST=${(await api<{ groups: { name: string }[] }>("/api/groups")).groups
          .map((g) => g.name)
          .join(",")}`,
      ];
      const content = lines.join("\n");
      await navigator.clipboard?.writeText(content);
      return content;
    },
    onSuccess: () => toast({ kind: "success", message: ".env 内容已复制（Key 为占位符，需手填）。" }),
  });

  if (boot.isLoading || settings.isLoading) return <Skeleton rows={6} />;

  return (
    <div className="space-y-4 max-w-[720px]">
      <Card title="外观">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[13px]">主题</span>
            <Select
              value={theme}
              onChange={(t) => setTheme(t === "light" ? "light" : "dark")}
              options={[
                { value: "dark", label: "暗色（默认）" },
                { value: "light", label: "亮色" },
              ]}
              className="w-40"
            />
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px]">界面模式</p>
              <p className="text-[11px] text-ink-muted">简单模式只显示高频页面；只是视图过滤，不丢数据。</p>
            </div>
            <Select
              value={mode}
              onChange={(m) => setMode(m as "simple" | "advanced")}
              options={[
                { value: "simple", label: "简单模式" },
                { value: "advanced", label: "高级模式" },
              ]}
              className="w-40"
            />
          </div>
        </div>
      </Card>

      <Card title="运行环境">
        <div className="space-y-3">
          <Field label="数据目录（全部配置与日志都在这里）">
            <Input value={boot.data!.data_dir} readOnly className="mono" />
          </Field>
          <Field label="桥接方式">
            <Select
              value={bridge}
              onChange={setBridge}
              options={[
                { value: "mock", label: "mock（本机沙箱）" },
                { value: "wxhook", label: "wxhook（微信 4.1.10.27 + hook）" },
                { value: "pyweixin", label: "pyweixin（UI 自动化）" },
              ]}
            />
          </Field>
          <Field label="时区">
            <Input value={tz} onChange={(e) => setTz(e.target.value)} />
          </Field>
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              loading={save.isPending}
              onClick={() =>
                save.mutate({ "bridge.mode": bridge, "schedule.timezone": tz })
              }
            >
              保存运行环境
            </Button>
            <Badge>{boot.data!.mode === "packaged" ? "发布版" : "开发模式"}</Badge>
          </div>
        </div>
      </Card>

      <Card
        title="导出"
        actions={
          <Button size="sm" loading={exportEnv.isPending} onClick={() => exportEnv.mutate()}>
            导出 .env 到剪贴板
          </Button>
        }
      >
        <p className="text-xs text-ink-muted leading-relaxed">
          .env 是 CLI 用户的格式。导出时密钥以占位符代替（任何导出物都不含明文密钥）。
        </p>
      </Card>
    </div>
  );
}
