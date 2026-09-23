/** 备份与诊断：环境体检清单 + 备份/恢复闭环。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApiQuery, type Diagnostic } from "../api/hooks";
import { RiskBanner } from "../components/RiskBanner";
import { Badge, Button, Card, ErrorState, Modal, Skeleton } from "../components/ui";
import { useUI } from "../store/ui";

type Backup = { name: string; path: string; size: number; ts: number };

export function System() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const diag = useApiQuery<Diagnostic>(["diagnostics"], "/api/diagnostics");
  const backups = useApiQuery<{ backups: Backup[] }>(["backups"], "/api/backup");
  const [restoring, setRestoring] = useState<Backup | null>(null);

  const backup = useMutation({
    mutationFn: () =>
      api<{ name: string }>("/api/backup", {
        method: "POST",
        body: JSON.stringify({ note: "手动备份" }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["backups"] });
      toast({ kind: "success", message: "备份完成（config.db + 角色包 + 白名单）。" });
    },
    onError: (e) => toast({ kind: "error", message: `备份失败：${String(e)}` }),
  });
  const restore = useMutation({
    mutationFn: (b: Backup) =>
      api("/api/restore", { method: "POST", body: JSON.stringify({ path: b.path }) }),
    onSuccess: () => {
      void qc.invalidateQueries();
      setRestoring(null);
      toast({ kind: "success", message: "已恢复（Core 已停止，按需重新启动）。" });
    },
    onError: (e) => toast({ kind: "error", message: `恢复失败：${String(e)}` }),
  });

  if (diag.isLoading) return <Skeleton rows={6} />;
  if (diag.isError || !diag.data)
    return <ErrorState error={diag.error} onRetry={() => diag.refetch()} />;

  const worst = diag.data.summary.fail > 0 ? "fail" : diag.data.summary.warn > 0 ? "warn" : "ok";

  return (
    <div className="space-y-4 max-w-[860px]">
      {worst !== "ok" && (
        <RiskBanner
          text={`体检发现 ${diag.data.summary.fail} 项失败、${diag.data.summary.warn} 项提醒（微信版本不符属预期橙警）。`}
        />
      )}

      <Card title="环境体检">
        <div className="space-y-1">
          {diag.data.checks.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-3 py-2 border-b border-line/60 last:border-0"
            >
              <Badge tone={c.status === "ok" ? "success" : c.status === "warn" ? "warning" : "danger"}>
                {c.status === "ok" ? "正常" : c.status === "warn" ? "提醒" : "失败"}
              </Badge>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] truncate">{c.detail}</p>
                {c.hint && <p className="text-[11px] text-ink-muted">{c.hint}</p>}
              </div>
              <span className="mono text-[10px] text-ink-muted">{c.id}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card
        title="本地备份"
        actions={
          <Button size="sm" variant="primary" loading={backup.isPending} onClick={() => backup.mutate()}>
            立即备份
          </Button>
        }
      >
        {backups.isLoading ? (
          <Skeleton rows={2} />
        ) : (backups.data?.backups.length ?? 0) === 0 ? (
          <p className="text-xs text-ink-muted">暂无备份。备份含配置库与角色包，不含语料索引。</p>
        ) : (
          <div className="space-y-1">
            {backups.data!.backups.map((b) => (
              <div
                key={b.name}
                className="flex items-center gap-3 border border-line rounded-[6px] px-2.5 py-2 text-[12px]"
              >
                <span className="mono text-[11px] flex-1 truncate">{b.name}</span>
                <span className="text-[10px] text-ink-muted">
                  {(b.size / 1024).toFixed(0)} KB
                </span>
                <Button size="sm" variant="ghost" onClick={() => setRestoring(b)}>
                  恢复
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal
        open={Boolean(restoring)}
        onClose={() => setRestoring(null)}
        title={`恢复备份 ${restoring?.name ?? ""}`}
        footer={
          <>
            <Button onClick={() => setRestoring(null)}>取消</Button>
            <Button
              variant="danger"
              loading={restore.isPending}
              onClick={() => restoring && restore.mutate(restoring)}
            >
              覆盖当前配置并恢复
            </Button>
          </>
        }
      >
        <p className="text-xs leading-relaxed">
          恢复会先停止机器人，然后用备份替换 config.db 与角色包；语料索引不受影响（如索引损坏，恢复后可在语料库页重建）。
        </p>
      </Modal>
    </div>
  );
}
