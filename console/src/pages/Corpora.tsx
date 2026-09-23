/** 语料库：卡片墙 + 检索测试台（证据 Top5 + 回复 + 耗时）+ 重建/导入。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api/client";
import { useApiQuery, type Corpus } from "../api/hooks";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Skeleton,
} from "../components/ui";
import { useUI } from "../store/ui";

type TestQueryResult = {
  evidence: { title: string; citation: string; text: string; speaker: string }[];
  covered: boolean;
  answer: string;
  corpus: string;
  elapsed_ms: number;
  note?: string;
};

type Task = { status: string; log: string[]; error?: string };

export function Corpora() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const list = useApiQuery<{ corpora: Corpus[] }>(["corpora"], "/api/corpora");
  const [question, setQuestion] = useState("阿米娅的档案里说了什么？");
  const [withAnswer, setWithAnswer] = useState(false);
  const [taskMap, setTaskMap] = useState<Record<string, string>>({});

  const test = useMutation({
    mutationFn: () =>
      api<TestQueryResult>("/api/corpora/test-query", {
        method: "POST",
        body: JSON.stringify({ question, with_answer: withAnswer }),
      }),
  });
  const reindex = useMutation({
    mutationFn: (id: string) =>
      api<{ task_id: string }>(`/api/corpora/${id}/reindex`, { method: "POST" }),
    onSuccess: (r, id) => {
      setTaskMap((m) => ({ ...m, [id]: r.task_id }));
      toast({ kind: "info", message: "索引重建已排队（已先停止 Core，完成后自动拉起）。" });
      pollTask(r.task_id);
    },
  });
  const importDb = useMutation({
    mutationFn: (path: string) =>
      api<{ imported: string; kind: string }>("/api/corpora/import", {
        method: "POST",
        body: JSON.stringify({ path }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["corpora"] });
      toast({ kind: "success", message: "导入完成。" });
    },
    onError: (e) => toast({ kind: "error", message: `导入失败：${String(e)}` }),
  });

  const pollTask = (tid: string) => {
    const timer = setInterval(async () => {
      try {
        const t = await api<Task>(`/api/corpora/tasks/${tid}`);
        if (t.status !== "running") {
          clearInterval(timer);
          void qc.invalidateQueries({ queryKey: ["corpora"] });
          toast(
            t.status === "done"
              ? { kind: "success", message: "索引重建完成。" }
              : { kind: "error", message: `重建失败：${t.error ?? ""}` },
          );
        }
      } catch {
        clearInterval(timer);
      }
    }, 2000);
  };

  if (list.isLoading) return <Skeleton rows={6} />;
  if (list.isError || !list.data) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;

  const corpora = list.data.corpora;

  return (
    <div className="space-y-4 max-w-[980px]">
      <Card
        title="语料库"
        actions={
          <ImportCorpus onImport={(p) => importDb.mutate(p)} loading={importDb.isPending} />
        }
      >
        {corpora.length === 0 ? (
          <EmptyState
            title="还没有语料库"
            description="完整剧情问答需要语料包。可导入本地 zip 或指向已有 db；导入前沙箱仍会以人设直答回复。"
          />
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {corpora.map((c) => (
              <div key={c.id} className="border border-line rounded-[10px] p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium truncate">{c.name}</p>
                  <Badge
                    tone={
                      c.index_status === "ready"
                        ? "success"
                        : c.index_status === "building"
                          ? "info"
                          : c.index_status === "failed"
                            ? "danger"
                            : "neutral"
                    }
                  >
                    {c.index_status === "ready"
                      ? "就绪"
                      : c.index_status === "pending"
                        ? "未建库"
                        : c.index_status}
                  </Badge>
                </div>
                <p className="text-[11px] text-ink-muted mt-1.5">
                  文档 {c.doc_count.toLocaleString()} · 实体 {c.entity_count.toLocaleString()} ·{" "}
                  {(c.size / 1048576).toFixed(0)} MB
                </p>
                <div className="mt-2.5">
                  {taskMap[c.id] ? (
                    <span className="text-[11px] text-info">重建中（日志见日志页）…</span>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => reindex.mutate(c.id)}>
                      重建索引
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="检索测试台">
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <Field label="问题">
              <Input value={question} onChange={(e) => setQuestion(e.target.value)} />
            </Field>
          </div>
          <label className="flex items-center gap-1.5 text-xs text-ink-muted pb-1.5">
            <input
              type="checkbox"
              checked={withAnswer}
              onChange={(e) => setWithAnswer(e.target.checked)}
              className="accent-[#ff7a1a]"
            />
            同时生成回复（消耗少量 Token）
          </label>
          <Button
            variant="primary"
            loading={test.isPending}
            onClick={() => test.mutate()}
          >
            <Search size={14} /> 检索
          </Button>
        </div>

        {test.data && (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-ink-muted">
              {test.data.note ??
                `${test.data.corpus || "未选库"} · ${test.data.elapsed_ms}ms · ${
                  test.data.covered ? "命中语料" : "未命中（将走人设直答）"
                }`}
            </p>
            <div>
              <p className="text-xs font-medium mb-1.5">证据 Top-5</p>
              {test.data.evidence.length === 0 ? (
                <p className="text-[11px] text-ink-muted">无证据。</p>
              ) : (
                <ol className="space-y-1.5">
                  {test.data.evidence.map((e, i) => (
                    <li
                      key={i}
                      className="border border-line rounded-[6px] px-2.5 py-2 text-[11px]"
                    >
                      <p className="font-medium">
                        {i + 1}. 《{e.title}》
                        {e.speaker && <span className="text-ink-muted"> · {e.speaker}：</span>}
                      </p>
                      <p className="text-ink-muted mt-0.5">{e.text}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            {test.data.answer && (
              <div>
                <p className="text-xs font-medium mb-1.5">回复</p>
                <p className="bg-elevated border border-line rounded-[6px] px-3 py-2 text-[13px] whitespace-pre-wrap">
                  {test.data.answer}
                </p>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function ImportCorpus({
  onImport,
  loading,
}: {
  onImport: (path: string) => void;
  loading: boolean;
}) {
  const [path, setPath] = useState("");
  return (
    <div className="flex gap-2">
      <Input
        value={path}
        onChange={(e) => setPath(e.target.value)}
        placeholder="本地 db / 语料 zip 的完整路径"
        className="w-64"
      />
      <Button size="sm" disabled={!path.trim()} loading={loading} onClick={() => onImport(path.trim())}>
        导入
      </Button>
    </div>
  );
}
