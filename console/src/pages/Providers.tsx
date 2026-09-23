/** 模型与 API：Provider 卡 + 密钥三件套（DPAPI/掩码/日志脱敏）+ 测试连接。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApiQuery } from "../api/hooks";
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

type Provider = {
  id: number;
  kind: string;
  base_url: string;
  model: string;
  key_hint: string;
  has_key: boolean;
  enabled: number;
};

type TestResult = {
  ok: boolean;
  translated?: string;
  latency_ms?: number;
  model?: string;
  reply_preview?: string;
  error?: string;
};

const PRESETS: Record<string, { label: string; base_url: string; model: string }> = {
  deepseek: { label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-flash" },
  openai: { label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  zhipu: { label: "智谱", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  kimi: { label: "Kimi", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  openrouter: { label: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "deepseek/deepseek-chat" },
};

export function Providers() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const q = useApiQuery<{ providers: Provider[]; active_id: number | null }>(
    ["providers"],
    "/api/providers",
  );
  const [kind, setKind] = useState("deepseek");
  const [baseUrl, setBaseUrl] = useState(PRESETS.deepseek.base_url);
  const [model, setModel] = useState(PRESETS.deepseek.model);
  const [apiKey, setApiKey] = useState("");
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const body = JSON.stringify({ kind, base_url: baseUrl, model, api_key: apiKey });
      const existing = q.data?.providers.at(-1);
      if (existing?.has_key && !apiKey) {
        // 已有密钥且未重填：只改其他字段
        return api(`/api/providers/${existing.id}`, { method: "PUT", body });
      }
      if (existing) {
        return api(`/api/providers/${existing.id}`, { method: "PUT", body });
      }
      return api("/api/providers", { method: "POST", body });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["providers"] });
      void qc.invalidateQueries({ queryKey: ["bootstrap"] });
      toast({ kind: "success", message: "已保存（密钥以 DPAPI 密文落库）。" });
      setApiKey("");
    },
    onError: (e) => toast({ kind: "error", message: `保存失败：${String(e)}` }),
  });

  const test = useMutation({
    mutationFn: async () => {
      const existing = q.data?.providers.at(-1);
      if (!existing) throw new Error("请先保存");
      return api<TestResult>(`/api/providers/${existing.id}/test`, { method: "POST" });
    },
    onSuccess: (r) => {
      setTestResult(r);
      toast(
        r.ok
          ? { kind: "success", message: `连接成功：${r.model} · ${r.latency_ms}ms。` }
          : { kind: "error", message: r.translated ?? "测试失败。" },
      );
    },
  });

  if (q.isLoading) return <Skeleton rows={5} />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const current = q.data.providers.at(-1) ?? null;

  return (
    <div className="space-y-4 max-w-[760px]">
      <Card title="服务商预设">
        <div className="grid grid-cols-5 gap-2">
          {Object.entries(PRESETS).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => {
                setKind(key);
                setBaseUrl(preset.base_url);
                setModel(preset.model);
              }}
              className={`p-2.5 rounded-[10px] border text-[13px] transition-colors ${
                kind === key
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-line hover:border-line-strong"
              }`}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title="密钥与接口"
        actions={
          current && (
            <Badge tone={current.has_key ? "success" : "warning"}>
              {current.has_key ? `已存密钥 ${current.key_hint}` : "未存密钥"}
            </Badge>
          )
        }
      >
        {q.data.providers.length === 0 && !current && (
          <EmptyState title="尚未配置模型服务" description="选预设、贴 Key、测试连接三步完成。" />
        )}
        <div className="space-y-3">
          <Field label="API Key（保存后以密文存储，界面永不回显）">
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                current?.has_key ? `已保存（${current.key_hint}），留空则不修改` : "sk-…"
              }
              autoComplete="off"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="接口地址">
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </Field>
            <Field label="模型">
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
            </Field>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
              保存
            </Button>
            <Button loading={test.isPending} disabled={!current} onClick={() => test.mutate()}>
              测试连接
            </Button>
            {testResult && (
              <Badge tone={testResult.ok ? "success" : "danger"}>
                {testResult.ok
                  ? `三绿灯通过 · ${testResult.latency_ms}ms · ${testResult.model}`
                  : (testResult.translated ?? "失败")}
              </Badge>
            )}
          </div>
          {testResult && !testResult.ok && (
            <p className="text-[11px] text-ink-muted">
              原始错误：{testResult.error?.slice(0, 120)}
            </p>
          )}
        </div>
      </Card>

      <Card title="安全说明">
        <ul className="text-[11px] text-ink-muted space-y-1 list-disc pl-4">
          <li>密钥仅以 Windows DPAPI 密文保存在本机 config.db（绑定当前用户）。</li>
          <li>界面与日志只显示掩码（sk-****xxxx）；网关日志自动脱敏。</li>
          <li>导出任何配置都会剥离密钥字段并提示去除数量。</li>
        </ul>
      </Card>
    </div>
  );
}
