/** 测试沙箱：左侧模拟器（群成员/私聊/@/文本）+ 右侧结果面板（回复/证据/提示词/耗时）。 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FlaskConical, Send } from "lucide-react";
import { api, translateError } from "../api/client";
import { useApiQuery, type SandboxResult } from "../api/hooks";
import { useBootstrap } from "../App";
import { Badge, Button, Card, Field, Input, Select, Skeleton } from "../components/ui";

export function SandboxPage() {
  const boot = useBootstrap();
  const personas = useApiQuery<{ personas: { id: string; wechat_name: string; at_aliases: string[] }[] }>(
    ["personas"],
    "/api/personas",
  );
  const activeId = boot.data?.character ?? "pelica";
  const active = personas.data?.personas.find((p) => p.id === activeId);
  const botName = active?.wechat_name || "佩丽卡";
  const alias = active?.at_aliases?.[0] || botName;

  const [text, setText] = useState(`@${alias} 你好`);
  const [sender, setSender] = useState("管理员");
  const [room, setRoom] = useState("沙箱群");
  const [scope, setScope] = useState("group");
  const [result, setResult] = useState<SandboxResult | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);

  // 当前生效角色变化时，同步默认消息（仅在用户未改过输入时替换）
  useEffect(() => {
    setText((prev) =>
      prev === "@佩丽卡 你好" || /^@[^ ]+ 你好$/.test(prev) ? `@${alias} 你好` : prev,
    );
  }, [alias]);

  const run = useMutation({
    mutationFn: () =>
      api<SandboxResult>("/api/sandbox/run", {
        method: "POST",
        body: JSON.stringify({
          text,
          sender,
          room,
          is_at: true,
          private: scope === "private",
        }),
      }),
    onSuccess: setResult,
    onError: (err) => {
      const t = translateError(err);
      setResult(null);
      alert(t.message);
    },
  });

  return (
    <div className="max-w-[1000px] grid grid-cols-2 gap-4">
      <Card title={`模拟器（当前角色：${botName}，跑的就是当前有效配置）`}>
        <div className="space-y-3">
          <Field label="身份">
            <Select
              value={scope}
              onChange={setScope}
              options={[
                { value: "group", label: "群成员（沙箱群）" },
                { value: "private", label: "私聊对方" },
              ]}
            />
          </Field>
          <Field label="发送者昵称">
            <Input value={sender} onChange={(e) => setSender(e.target.value)} />
          </Field>
          {scope === "group" && (
            <Field label="群名">
              <Input value={room} onChange={(e) => setRoom(e.target.value)} />
            </Field>
          )}
          <Field label={`消息（以 @${alias} 开头表示 @ 了机器人）`}>
            <Input value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
            <Send size={14} /> 发送（不碰真实微信）
          </Button>
          <p className="text-[11px] text-ink-muted">
            完整管道：触发判定 → 白名单 → 检索 → 人设提示词 → LLM → 拆条。首次约 3-8 秒。
            切换角色请到「方案中心」应用方案，这里立即跟随。
          </p>
        </div>
      </Card>

      <Card title="结果">
        {run.isPending ? (
          <div className="space-y-2">
            <p className="text-xs text-ink-muted">思考中……</p>
            <Skeleton rows={3} />
          </div>
        ) : !result ? (
          <p className="text-xs text-ink-muted">发送一条消息开始测试。</p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              {result.replies.length === 0 ? (
                <p className="text-xs text-warning">
                  机器人保持沉默（可能被频控/白名单拦截，或消息不像问题）。
                </p>
              ) : (
                result.replies.map((r, i) => (
                  <p
                    key={i}
                    className="bg-elevated border border-line rounded-[10px] px-3 py-2 text-[13px]"
                  >
                    {r}
                  </p>
                ))
              )}
            </div>

            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <Badge tone={result.llm_key_configured ? "success" : "warning"}>
                {result.llm_key_configured ? "LLM 已配置" : "无 Key（人设兜底）"}
              </Badge>
              <Badge>{result.character}</Badge>
              {result.corpus_db ? (
                <Badge tone={result.evidence_covered ? "success" : "neutral"}>
                  {result.evidence_covered ? "证据命中" : "无语料证据"}
                </Badge>
              ) : (
                <Badge tone="warning">无语料库</Badge>
              )}
              <Badge>{result.elapsed_s}s</Badge>
            </div>

            {result.evidence.length > 0 && (
              <div>
                <p className="text-xs font-medium mb-1.5">证据</p>
                <ol className="space-y-1">
                  {result.evidence.map((e, i) => (
                    <li key={i} className="text-[11px] border border-line rounded px-2 py-1.5">
                      {i + 1}. 《{e.title}》{e.speaker ? ` · ${e.speaker}：` : ""}
                      <span className="text-ink-muted">{e.text.slice(0, 120)}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <div>
              <button
                className="flex items-center gap-1.5 text-xs text-accent hover:underline"
                onClick={() => setShowPrompt(!showPrompt)}
              >
                <FlaskConical size={12} aria-hidden />
                {showPrompt ? "收起提示词" : "查看完整提示词"}
              </button>
              {showPrompt && (
                <div className="mt-2 space-y-2">
                  <div>
                    <p className="text-[10px] text-ink-muted mb-1">SYSTEM</p>
                    <pre className="bg-base border border-line rounded p-2 text-[10px] font-mono whitespace-pre-wrap max-h-52 overflow-auto">
                      {result.system_prompt}
                    </pre>
                  </div>
                  <div>
                    <p className="text-[10px] text-ink-muted mb-1">USER（重建展示）</p>
                    <pre className="bg-base border border-line rounded p-2 text-[10px] font-mono whitespace-pre-wrap max-h-52 overflow-auto">
                      {result.user_prompt}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
