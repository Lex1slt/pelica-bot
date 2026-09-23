/** 日志与审计：实时 WS 流（级别筛选/暂停/搜索）+ 审计时间线（可撤销）。 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Undo2 } from "lucide-react";
import { api, logWsUrl } from "../api/client";
import { useApiQuery, type AuditRow } from "../api/hooks";
import { Badge, Button, Card, ErrorState, Input, Skeleton, Tabs } from "../components/ui";
import { useUI } from "../store/ui";

type LogEntry = { ts: string; source: string; level: string; message: string };

export function Logs() {
  const [tab, setTab] = useState("live");
  return (
    <div className="max-w-[1000px]">
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "live", label: "实时日志" },
          { value: "audit", label: "审计" },
        ]}
      >
        {tab === "live" ? <LiveLogs /> : <AuditTimeline />}
      </Tabs>
    </div>
  );
}

function LiveLogs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [level, setLevel] = useState("all");
  const [search, setSearch] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;
    const connect = () => {
      void logWsUrl().then((url) => {
        ws = new WebSocket(url);
        ws.onmessage = (ev) => {
          if (pausedRef.current) return;
          try {
            const data = JSON.parse(ev.data as string) as
              | { type: "backlog"; logs: LogEntry[] }
              | { type: "log"; log: LogEntry };
            if (data.type === "backlog") setLogs(data.logs);
            else setLogs((prev) => [...prev.slice(-500), data.log]);
          } catch {
            /* 非 JSON 帧忽略 */
          }
        };
        ws.onclose = () => {
          if (!closed) retry = window.setTimeout(connect, 3000);
        };
      });
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    if (!paused && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight;
    }
  }, [logs, paused]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.filter(
      (l) =>
        (level === "all" || l.level === level) &&
        (!q || l.message.toLowerCase().includes(q)),
    );
  }, [logs, level, search]);

  return (
    <Card
      title="实时日志（网关 + Core 子进程，已自动脱敏）"
      actions={
        <>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索…"
            className="h-7 w-40 text-xs"
          />
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="bg-base border border-line rounded-[6px] h-7 text-xs px-1.5"
            aria-label="级别筛选"
          >
            <option value="all">全部级别</option>
            <option value="info">INFO</option>
            <option value="warning">WARN</option>
            <option value="error">ERROR</option>
          </select>
          <Button size="sm" onClick={() => setPaused(!paused)}>
            {paused ? <Play size={12} /> : <Pause size={12} />}
            {paused ? "继续" : "暂停"}
          </Button>
        </>
      }
    >
      <div
        ref={boxRef}
        className="bg-base border border-line rounded-[6px] p-2.5 h-[420px] overflow-auto font-mono text-[11px] leading-relaxed"
      >
        {filtered.length === 0 && <p className="text-ink-muted">暂无日志。</p>}
        {filtered.map((l, i) => (
          <p key={i} className="whitespace-pre-wrap">
            <span className="text-ink-muted/70">{l.ts} </span>
            <span
              className={
                l.level === "error"
                  ? "text-danger"
                  : l.level === "warning"
                    ? "text-warning"
                    : "text-info"
              }
            >
              [{l.source}/{l.level}]
            </span>{" "}
            {l.message}
          </p>
        ))}
      </div>
    </Card>
  );
}

function AuditTimeline() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const q = useApiQuery<{ audit: AuditRow[] }>(["audit"], "/api/audit?limit=100");
  const undo = useMutation({
    mutationFn: (id: number) => api(`/api/audit/${id}/undo`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "已撤销（相关配置已回滚）。" });
    },
    onError: (e) => toast({ kind: "error", message: `撤销失败：${String(e)}` }),
  });

  if (q.isLoading) return <Skeleton rows={6} />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <Card title="审计时间线（所有写操作先落快照，可撤销）">
      {q.data.audit.length === 0 ? (
        <p className="text-xs text-ink-muted">暂无操作记录。</p>
      ) : (
        <div className="space-y-1">
          {q.data.audit.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-2.5 border border-line rounded-[6px] px-2.5 py-2 text-[12px]"
            >
              <span className="mono text-[10px] text-ink-muted shrink-0">#{a.id}</span>
              <Badge>{a.action}</Badge>
              <span className="mono text-[10px] text-ink-muted truncate flex-1">
                {a.target}
              </span>
              <span className="text-[10px] text-ink-muted shrink-0">
                {a.ts} · {a.actor}
              </span>
              {a.undoable && (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={undo.isPending && undo.variables === a.id}
                  onClick={() => undo.mutate(a.id)}
                >
                  <Undo2 size={12} /> 撤销
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
