/** 功能开关：简单模式三套餐卡 + 高级模式开关墙 + 定时任务（全模式可见）。 */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { api } from "../api/client";
import { useApiQuery, type FlagDefs } from "../api/hooks";
import { Badge, Button, Card, ErrorState, Field, Input, Select, Skeleton, Switch } from "../components/ui";
import { useUI } from "../store/ui";

type Preset = {
  name: string;
  label: string;
  description: string;
  flags: Record<string, boolean>;
  diff: string[];
};

export function Flags() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const mode = useUI((s) => s.mode);
  const flags = useApiQuery<FlagDefs>(["flags"], "/api/flags");
  const presets = useApiQuery<{ presets: Preset[] }>(["presets"], "/api/flags/presets");

  const applyPreset = useMutation({
    mutationFn: (name: string) =>
      api(`/api/flags/presets/${name}/apply`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "套餐已应用（运行中的机器人将自动重启注入）。" });
    },
  });
  const toggleFlag = useMutation({
    mutationFn: (payload: Record<string, boolean>) =>
      api("/api/flags", { method: "PUT", body: JSON.stringify({ flags: payload }) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["flags"] }),
  });

  // ── 定时任务与自动化（schedule.* 设置键，Core 重启/自动重启后生效） ────
  const settings = useApiQuery<Record<string, unknown>>(["settings"], "/api/settings");
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!settings.data || Object.keys(draft).length) return;
    const s = settings.data;
    const pick = (k: string, d: string) => String(s[k] ?? d);
    setDraft({
      "schedule.greeting_morning": pick("schedule.greeting_morning", "07:30"),
      "schedule.greeting_night": pick("schedule.greeting_night", "23:00"),
      "schedule.weekly_time": pick("schedule.weekly_time", "18:00"),
      "schedule.weekly_weekday": pick("schedule.weekly_weekday", "fri"),
      "schedule.greeting_days": pick("schedule.greeting_days", "3"),
      "douyin.keep_hours": pick("douyin.keep_hours", "48"),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.data]);

  const saveSchedule = useMutation({
    mutationFn: () =>
      api("/api/settings", { method: "PUT", body: JSON.stringify({ values: draft }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings"] });
      toast({ kind: "success", message: "定时任务已保存（运行中的机器人会自动重启注入）。" });
    },
    onError: (e) => toast({ kind: "error", message: `保存失败：${String(e)}` }),
  });

  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  if (flags.isLoading) return <Skeleton rows={5} />;
  if (flags.isError || !flags.data)
    return <ErrorState error={flags.error} onRetry={() => flags.refetch()} />;

  return (
    <div className="space-y-4 max-w-[860px]">
      {mode === "simple" ? (
        <>
          <p className="text-xs text-ink-muted">
            一键切换整套行为；卡片下方列出与当前配置的差异。切换到高级模式可逐项控制。
          </p>
          <div className="grid grid-cols-3 gap-3">
            {(presets.data?.presets ?? []).map((p) => (
              <Card key={p.name}>
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold">{p.label}</p>
                  {p.name === "standard" && <Badge tone="accent">推荐</Badge>}
                </div>
                <p className="text-[11px] text-ink-muted mt-1.5 min-h-[36px]">
                  {p.description}
                </p>
                {p.diff.length > 0 ? (
                  <p className="text-[11px] text-warning mt-1.5">
                    与当前不同：{p.diff.join("、")}
                  </p>
                ) : (
                  <p className="text-[11px] text-success mt-1.5 flex items-center gap-1">
                    <CheckCircle2 size={12} aria-hidden /> 与当前一致
                  </p>
                )}
                <Button
                  size="sm"
                  variant={p.diff.length === 0 ? "secondary" : "primary"}
                  disabled={p.diff.length === 0}
                  loading={applyPreset.isPending && applyPreset.variables === p.name}
                  onClick={() => applyPreset.mutate(p.name)}
                  className="mt-3"
                >
                  {p.diff.length === 0 ? "当前套餐" : "应用"}
                </Button>
              </Card>
            ))}
          </div>
        </>
      ) : (
        <Card title="开关墙（全局作用域）">
          <div className="space-y-1">
            {flags.data.definitions.map((d) => (
              <div
                key={d.key}
                className="flex items-center gap-3 py-2.5 border-b border-line/60 last:border-0"
              >
                <Switch
                  checked={flags.data.effective[d.key] ?? true}
                  onChange={(v) => toggleFlag.mutate({ [d.key]: v })}
                  label={d.name}
                />
                <div className="flex-1">
                  <p className="text-[13px]">{d.name}</p>
                  <p className="text-[11px] text-ink-muted">{d.desc}</p>
                </div>
                <Badge>{d.group}</Badge>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-ink-muted mt-3">
            追问续聊（@ 后 3 分钟窗口）与自发插话（实体话题低概率搭话）为内核常开能力，受群/人双重冷却约束。
          </p>
        </Card>
      )}

      <Card title="定时任务与自动化（每天几点问好 / 周几发周报）">
        {settings.isLoading ? (
          <Skeleton rows={4} />
        ) : settings.isError || !settings.data ? (
          <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="每天早上问好时间">
                <Input
                  type="time"
                  value={draft["schedule.greeting_morning"] ?? "07:30"}
                  onChange={(e) => set("schedule.greeting_morning", e.target.value)}
                />
              </Field>
              <Field label="每天晚上问好时间">
                <Input
                  type="time"
                  value={draft["schedule.greeting_night"] ?? "23:00"}
                  onChange={(e) => set("schedule.greeting_night", e.target.value)}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="周报发送时间">
                <Input
                  type="time"
                  value={draft["schedule.weekly_time"] ?? "18:00"}
                  onChange={(e) => set("schedule.weekly_time", e.target.value)}
                />
              </Field>
              <Field label="周报发送日">
                <Select
                  value={draft["schedule.weekly_weekday"] ?? "fri"}
                  onChange={(v) => set("schedule.weekly_weekday", v)}
                  options={[
                    { value: "mon", label: "周一" },
                    { value: "tue", label: "周二" },
                    { value: "wed", label: "周三" },
                    { value: "thu", label: "周四" },
                    { value: "fri", label: "周五" },
                    { value: "sat", label: "周六" },
                    { value: "sun", label: "周日" },
                  ]}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="问好目标群：最近几天有动静才发">
                <Input
                  type="number"
                  min={1}
                  max={30}
                  value={draft["schedule.greeting_days"] ?? "3"}
                  onChange={(e) => set("schedule.greeting_days", e.target.value)}
                />
              </Field>
              <Field label="抖音/B 站视频缓存保留（小时）">
                <Input
                  type="number"
                  min={1}
                  value={draft["douyin.keep_hours"] ?? "48"}
                  onChange={(e) => set("douyin.keep_hours", e.target.value)}
                />
              </Field>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                loading={saveSchedule.isPending}
                onClick={() => saveSchedule.mutate()}
              >
                保存定时设置
              </Button>
              <p className="text-[11px] text-ink-muted">
                保存后自动重启机器人内核生效；问好只发给最近有动静的群。
              </p>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
