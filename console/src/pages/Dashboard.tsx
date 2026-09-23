/** 仪表盘：实时机器人/微信桥接状态（3s 轮询）+ 启停/断联控制 + 健康度。 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, ChevronDown, Link2Off, Play, Square } from "lucide-react";
import { api } from "../api/client";
import { useBootstrap } from "../App";
import { useCoreStatus, type Diagnostic } from "../api/hooks";
import { RiskBanner } from "../components/RiskBanner";
import { Badge, Button, Card, Skeleton, StatusDot } from "../components/ui";
import { useUI } from "../store/ui";

export function Dashboard() {
  const boot = useBootstrap();
  const toast = useUI((s) => s.toast);
  const status = useCoreStatus();
  const [riskOpen, setRiskOpen] = useState(true);
  const diag = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => api<Diagnostic>("/api/diagnostics"),
    refetchInterval: 30_000,
  });
  const core = useMutation({
    mutationFn: (action: "start" | "stop" | "restart") =>
      api(`/api/core/${action}`, { method: "POST" }),
    onSuccess: () => {
      void boot.refetch();
      toast({ kind: "success", message: "指令已执行。" });
    },
  });

  if (boot.isLoading) return <Skeleton rows={6} />;
  const data = boot.data!;
  const running = status.data?.core.running ?? false;
  const bridge = status.data?.bridge;

  return (
    <div className="space-y-4 max-w-[900px]">
      {riskOpen ? (
        <RiskBanner
          text="当前使用注入式桥接，建议使用小号运营。全局冷却 ≥30s、每日上限、静默时段等保守频控建议见安全建议。"
          actionLabel="收起"
          onAction={() => setRiskOpen(false)}
        />
      ) : (
        <button
          className="text-xs text-ink-muted hover:text-ink flex items-center gap-1"
          onClick={() => setRiskOpen(true)}
        >
          <ChevronDown size={12} /> 显示安全提示
        </button>
      )}

      <div className="grid grid-cols-3 gap-3">
        <Card>
          <div className="flex items-center justify-between">
            <p className="text-xs text-ink-muted">机器人</p>
            <StatusDot status={running ? "running" : "off"} />
          </div>
          <p className="text-lg font-semibold mt-1.5">
            {status.isLoading ? "…" : running ? "运行中" : "未运行"}
          </p>
          <p className="text-[11px] text-ink-muted">
            {running
              ? `pid ${status.data!.core.pid} · 已运行 ${Math.floor((status.data!.core.uptime_s ?? 0) / 60)} 分`
              : "点击下方启动"}
          </p>
          <div className="flex gap-2 mt-3">
            {running ? (
              <Button size="sm" loading={core.isPending} onClick={() => core.mutate("stop")}>
                <Square size={13} /> 停止
              </Button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                loading={core.isPending}
                onClick={() => core.mutate("start")}
              >
                <Play size={13} /> 启动
              </Button>
            )}
            <Button size="sm" disabled={!running} loading={core.isPending} onClick={() => core.mutate("restart")}>
              重启
            </Button>
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <p className="text-xs text-ink-muted">微信连接</p>
            <StatusDot
              status={
                bridge?.mode === "mock"
                  ? running
                    ? "ok"
                    : "off"
                  : bridge?.connected
                    ? "running"
                    : running
                      ? "warn"
                      : "off"
              }
            />
          </div>
          <p className="text-lg font-semibold mt-1.5">
            {bridge?.mode === "mock"
              ? running
                ? "沙箱模式"
                : "未接入"
              : bridge?.connected
                ? "已连接"
                : running
                  ? "未连上"
                  : "未接入"}
          </p>
          <p className="text-[11px] text-ink-muted">{bridge?.detail ?? " "}</p>
          {running ? (
            <Button
              size="sm"
              variant="danger"
              loading={core.isPending}
              onClick={() => core.mutate("stop")}
              className="mt-3"
            >
              <Link2Off size={13} /> 断开连接
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              loading={core.isPending}
              onClick={() => core.mutate("start")}
              className="mt-3"
            >
              <Play size={13} /> 连接微信
            </Button>
          )}
        </Card>

        <Card>
          <p className="text-xs text-ink-muted">当前角色</p>
          <p className="text-lg font-semibold mt-1.5 flex items-center gap-2">
            <Bot size={16} aria-hidden /> {data.character}
          </p>
          <div className="flex gap-1.5 mt-2">
            <Badge tone={data.provider?.has_key ? "success" : "warning"}>
              {data.provider ? `${data.provider.kind} · ${data.provider.key_hint || "未填 Key"}` : "未配置模型"}
            </Badge>
          </div>
        </Card>
      </div>

      <Card title="健康度体检（30s 刷新）">
        {diag.isLoading ? (
          <Skeleton rows={2} />
        ) : diag.data ? (
          <>
            <p className="text-[13px]">
              <span className="font-semibold">{diag.data.summary.ok} 项正常</span>
              {diag.data.summary.fail > 0 && (
                <span className="text-danger"> · {diag.data.summary.fail} 项失败</span>
              )}
              {diag.data.summary.warn > 0 && (
                <span className="text-warning"> · {diag.data.summary.warn} 项提醒</span>
              )}
            </p>
            <ul className="mt-2 space-y-1">
              {diag.data.checks
                .filter((c) => c.status !== "ok")
                .map((c) => (
                  <li key={c.id} className="flex items-center gap-1.5 text-[11px]">
                    <StatusDot status={c.status === "fail" ? "fail" : "warn"} />
                    <span className="truncate">{c.detail}</span>
                  </li>
                ))}
            </ul>
          </>
        ) : (
          <p className="text-xs text-danger">诊断不可用</p>
        )}
      </Card>

      <Card title="数据一览">
        <div className="grid grid-cols-4 gap-3 text-center">
          <div>
            <p className="text-xl font-semibold">{data.groups_count}</p>
            <p className="text-[11px] text-ink-muted">启用群</p>
          </div>
          <div>
            <p className="text-xl font-semibold">{data.personas.length}</p>
            <p className="text-[11px] text-ink-muted">角色包</p>
          </div>
          <div>
            <p className="text-xl font-semibold">{data.has_corpus ? "已就绪" : "未导入"}</p>
            <p className="text-[11px] text-ink-muted">语料库</p>
          </div>
          <div>
            <p className="text-xl font-semibold mono">{data.mode}</p>
            <p className="text-[11px] text-ink-muted">运行模式</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
