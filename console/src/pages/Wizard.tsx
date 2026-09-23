/** 首启向导 8 步（设计 §3：目标 8 分 30 秒路径；中断重开续走）。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, FlaskConical } from "lucide-react";
import { api } from "../api/client";
import { useBootstrap } from "../App";
import { RiskBanner } from "../components/RiskBanner";
import { Badge, Button, Field, Input, Select, Skeleton, Switch } from "../components/ui";
import { useUI } from "../store/ui";

const RISK_TEXT =
  "本程序的微信接入方式（WeChat-Hook）通过 DLL 注入修改微信客户端行为，不属于微信官方支持的接口。使用本程序存在账号被限制或封禁的风险。强烈建议：仅使用小号运行本程序；不要在承载重要账号的电脑上同时使用 hook。";

const STEPS = [
  "欢迎",
  "风险告知",
  "连接微信",
  "选择方案",
  "模型密钥",
  "沙箱试聊",
  "启用群聊",
  "完成",
];

export function Wizard() {
  const boot = useBootstrap();
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const [step, setStep] = useState(() =>
    Math.min((boot.data?.wizard.current_step ?? 0) || 0, 7),
  );
  const [riskAccepted, setRiskAccepted] = useState(false);
  const [bridge, setBridge] = useState("mock");
  const [character, setCharacter] = useState(boot.data?.character ?? "pelica");
  const [apiKey, setApiKey] = useState("");
  const [keyVisible, setKeyVisible] = useState(false);
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com/v1");
  const [model, setModel] = useState("deepseek-flash");
  const [sandboxOk, setSandboxOk] = useState<boolean | null>(null);
  const [autostartWanted, setAutostartWanted] = useState(false);
  const [groups, setGroups] = useState<{ name: string; wxid: string; on: boolean }[]>([
    { name: "示例群（先拿它试）", wxid: "", on: true },
  ]);

  const stepMutation = useMutation({
    mutationFn: (payload: { step: number; payload: Record<string, unknown> }) =>
      api("/api/wizard/step", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bootstrap"] }),
  });

  const testProvider = useMutation({
    mutationFn: async () => {
      await stepMutation.mutateAsync({
        step: 5,
        payload: { provider: { kind: "deepseek", base_url: baseUrl, model, api_key: apiKey } },
      });
      const providers = await api<{ providers: { id: number }[] }>("/api/providers");
      const id = providers.providers.at(-1)?.id;
      if (id == null) throw new Error("provider 未创建");
      return api<{ ok: boolean; translated?: string; latency_ms?: number }>(
        `/api/providers/${id}/test`,
        { method: "POST" },
      );
    },
  });

  if (boot.isLoading) return <Skeleton rows={5} />;

  const personas = boot.data?.personas ?? ["pelica"];
  const next = async () => {
    const current = step;
    if (current === 1 && !riskAccepted) return;
    if (current === 2) {
      await stepMutation.mutateAsync({ step: 3, payload: { bridge } }).catch(() => {});
    }
    if (current === 3) {
      await stepMutation.mutateAsync({ step: 4, payload: { character } }).catch(() => {});
    }
    if (current === 6) {
      await stepMutation.mutateAsync({
        step: 7,
        payload: { groups: groups.filter((g) => g.on) },
      }).catch(() => {});
    }
    if (current === 7) {
      await stepMutation.mutateAsync({ step: 8, payload: {} }).catch(() => {});
    }
    setStep(Math.min(current + 1, 7));
  };
  const prev = () => setStep(Math.max(step - 1, 0));

  return (
    <div className="h-full flex flex-col items-center justify-center p-6">
      <div className="w-[640px] max-w-full">
        <header className="mb-5">
          <p className="text-[11px] text-ink-muted mb-1">
            Pelica Console · 首次配置向导 {step + 1}/8
          </p>
          <h1 className="text-xl font-semibold">{STEPS[step]}</h1>
          <div className="flex gap-1 mt-3" aria-hidden>
            {STEPS.map((s, i) => (
              <span
                key={s}
                className={`h-1 flex-1 rounded-full transition-colors ${
                  i <= step ? "bg-accent" : "bg-line"
                }`}
              />
            ))}
          </div>
        </header>

        <div className="bg-surface border border-line rounded-[14px] p-5 min-h-[300px]">
          {step === 0 && (
            <div className="space-y-4">
              <p className="text-[13px] leading-relaxed">
                欢迎使用佩丽卡控制台。这个向导带你用 8 分钟完成首次配置：
                选方案 → 填密钥 → 沙箱试聊 → 启用一个群。
              </p>
              <RiskBanner
                text="当前使用注入式桥接，建议使用小号运营。向导第 2 步有完整风险告知。"
              />
              <p className="text-xs text-ink-muted">
                提示：全部数据只保存在本机；随时可按 Ctrl+K 搜索一切。
              </p>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <RiskBanner text={RISK_TEXT} />
              <label className="flex items-start gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={riskAccepted}
                  onChange={(e) => setRiskAccepted(e.target.checked)}
                  className="mt-0.5 accent-[#ff7a1a]"
                />
                <span className="text-[13px]">我已了解上述风险，将使用小号。</span>
              </label>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-[13px]">
                先选择微信接入方式。没有装好微信 4.1.10.27 + hook 也可以先用沙箱体验。
              </p>
              <Field label="桥接方式">
                <Select
                  value={bridge}
                  onChange={setBridge}
                  options={[
                    { value: "mock", label: "暂不连接（沙箱体验，推荐先选这个）" },
                    { value: "wxhook", label: "WeChat-Hook（微信 4.1.10.27 + version.dll）" },
                    { value: "pyweixin", label: "pyweixin UI 自动化（备用）" },
                  ]}
                />
              </Field>
              <p className="text-xs text-ink-muted">
                这一页随时可以跳过——不影响向导继续。
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <p className="text-[13px]">选一个角色方案（之后随时可换）。</p>
              <div className="grid grid-cols-3 gap-2">
                {personas.map((p) => (
                  <button
                    key={p}
                    onClick={() => setCharacter(p)}
                    className={`p-3 rounded-[10px] border text-left transition-colors ${
                      character === p
                        ? "border-accent bg-accent/10"
                        : "border-line hover:border-line-strong"
                    }`}
                  >
                    <p className="text-sm font-medium">
                      {p === "pelica" ? "🦉 佩丽卡" : p === "kaltsit" ? "🩺 凯尔希" : "✨ 派蒙"}
                    </p>
                    <p className="text-[11px] text-ink-muted mt-1">
                      {p === "pelica"
                        ? "终末地监督 · 默认"
                        : p === "kaltsit"
                          ? "罗德岛医疗主管"
                          : "原神语料（需导入）"}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-3">
              <p className="text-[13px]">填入模型 API Key（仅本机加密保存，界面不回显）。</p>
              <Field label="API Key">
                <div className="flex gap-2">
                  <Input
                    type={keyVisible ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-…（粘贴后以密文存入本机）"
                    autoComplete="off"
                  />
                  <Button size="sm" onClick={() => setKeyVisible(!keyVisible)}>
                    {keyVisible ? "隐藏" : "显示"}
                  </Button>
                </div>
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
                <Button
                  variant="primary"
                  loading={testProvider.isPending}
                  onClick={() =>
                    testProvider.mutate(undefined, {
                      onSuccess: (r) => {
                        if (r.ok) {
                          toast({ kind: "success", message: `连接成功（${r.latency_ms}ms）。` });
                        } else {
                          toast({ kind: "error", message: r.translated ?? "测试失败。" });
                        }
                      },
                      onError: (e) =>
                        toast({ kind: "error", message: `测试失败：${String(e)}` }),
                    })
                  }
                >
                  测试连接
                </Button>
                {testProvider.data && (
                  <Badge tone={testProvider.data.ok ? "success" : "danger"}>
                    {testProvider.data.ok
                      ? `绿灯 · ${testProvider.data.latency_ms}ms`
                      : (testProvider.data.translated ?? "失败")}
                  </Badge>
                )}
              </div>
            </div>
          )}

          {step === 5 && <WizardSandbox onResult={setSandboxOk} />}

          {step === 6 && (
            <div className="space-y-3">
              <p className="text-[13px]">
                启用哪些群？默认仅 @ 触发 + 保守频控（建议）。
              </p>
              {groups.map((g, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Switch
                    checked={g.on}
                    onChange={(v) =>
                      setGroups(groups.map((x, j) => (i === j ? { ...x, on: v } : x)))
                    }
                    label={`启用 ${g.name}`}
                  />
                  <Input
                    value={g.name}
                    onChange={(e) =>
                      setGroups(groups.map((x, j) => (i === j ? { ...x, name: e.target.value } : x)))
                    }
                    placeholder="群名（与微信里一致）"
                  />
                  <Input
                    value={g.wxid}
                    onChange={(e) =>
                      setGroups(groups.map((x, j) => (i === j ? { ...x, wxid: e.target.value } : x)))
                    }
                    placeholder="群 ID（可选）"
                    className="max-w-[160px]"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setGroups(groups.filter((_, j) => j !== i))}
                    aria-label="删除此群"
                  >
                    删除
                  </Button>
                </div>
              ))}
              <Button
                size="sm"
                onClick={() => setGroups([...groups, { name: "", wxid: "", on: true }])}
              >
                添加群
              </Button>
            </div>
          )}

          {step === 7 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-success">
                <CheckCircle2 size={18} aria-hidden />
                <p className="text-sm font-medium">配置完成。</p>
              </div>
              <p className="text-xs text-ink-muted leading-relaxed">
                {boot.data?.has_corpus
                  ? "已发现语料库，剧情问答就绪。"
                  : "提示：完整剧情问答需导入语料包（语料库页 → 导入本地 zip / 指向已有 db）。沙箱在人设直答模式下同样可用。"}
              </p>
              <label className="flex items-center gap-2.5 text-[13px] cursor-pointer">
                <Switch checked={autostartWanted} onChange={setAutostartWanted} label="开机自启" />
                开机自动启动 Pelica Console（可在设置里随时改）
              </label>
            </div>
          )}
        </div>

        <footer className="flex justify-between mt-4">
          <Button onClick={prev} disabled={step === 0}>
            <ArrowLeft size={14} /> 上一步
          </Button>
          {step === 5 ? (
            <div className="flex gap-2">
              {sandboxOk === false && (
                <Button
                  onClick={() => {
                    void stepMutation.mutateAsync({ step: 6, payload: {} });
                    setStep(6);
                  }}
                >
                  仍然完成
                </Button>
              )}
              <Button variant="primary" onClick={next}>
                下一步 <ArrowRight size={14} />
              </Button>
            </div>
          ) : step === 7 ? (
            <Button
              variant="primary"
              onClick={() => {
                void stepMutation
                  .mutateAsync({ step: 8, payload: {} })
                  .catch(() => {})
                  .then(() => {
                    if (autostartWanted) void enableAutostart();
                    void qc.invalidateQueries({ queryKey: ["bootstrap"] });
                    window.location.reload();
                  });
              }}
            >
              进入控制台
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => void next()}
              disabled={step === 1 && !riskAccepted}
            >
              下一步 <ArrowRight size={14} />
            </Button>
          )}
        </footer>
      </div>
    </div>
  );
}

async function enableAutostart() {
  try {
    const w = window as unknown as {
      __TAURI_INTERNALS__?: { invoke: (c: string, a?: unknown) => Promise<void> };
    };
    await w.__TAURI_INTERNALS__?.invoke("enable_autostart", { enable: true });
  } catch {
    /* 非 Tauri 环境忽略 */
  }
}

function WizardSandbox({ onResult }: { onResult: (ok: boolean) => void }) {
  const [text, setText] = useState("@佩丽卡 你好");
  const [replies, setReplies] = useState<string[]>([]);
  const [error, setError] = useState("");
  const run = useMutation({
    mutationFn: () =>
      api<{ replies: string[] }>("/api/sandbox/run", {
        method: "POST",
        body: JSON.stringify({ text, sender: "管理员", room: "沙箱群" }),
      }),
    onSuccess: (r) => {
      setReplies(r.replies);
      setError("");
      onResult(r.replies.length > 0);
    },
    onError: (e) => {
      setError(String(e));
      onResult(false);
    },
  });
  return (
    <div className="space-y-3">
      <p className="text-[13px]">
        给佩丽卡发条消息试试——不碰真实微信，跑的是完整管道。
      </p>
      <div className="flex gap-2">
        <Input value={text} onChange={(e) => setText(e.target.value)} />
        <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
          <FlaskConical size={14} /> 发送
        </Button>
      </div>
      {run.isPending && <p className="text-xs text-ink-muted">思考中（首次约 3-8 秒）……</p>}
      {replies.length > 0 && (
        <div className="space-y-1.5">
          {replies.map((r, i) => (
            <p
              key={i}
              className="bg-elevated border border-line rounded-[10px] px-3 py-2 text-[13px]"
            >
              {r}
            </p>
          ))}
        </div>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      {replies.length === 0 && !run.isPending && !error && (
        <p className="text-xs text-ink-muted">
          还没发送。此步失败不阻断——可直接点「仍然完成」。
        </p>
      )}
    </div>
  );
}
