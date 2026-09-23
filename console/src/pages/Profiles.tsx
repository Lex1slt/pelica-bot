/** 方案中心：内置三方案大卡 + 应用/复制 + 方案编辑器（人设提示词/语料库/API 可查看与编辑）+ 导入导出。 */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useApiQuery, type Corpus, type Persona, type Profile } from "../api/hooks";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Modal,
  Select,
  Skeleton,
  Textarea,
} from "../components/ui";
import { useUI } from "../store/ui";

const PROVIDER_KINDS = [
  { value: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com/v1" },
  { value: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1" },
  { value: "zhipu", label: "智谱", base_url: "https://open.bigmodel.cn/api/paas/v4" },
  { value: "kimi", label: "Kimi", base_url: "https://api.moonshot.cn/v1" },
  { value: "openrouter", label: "OpenRouter", base_url: "https://openrouter.ai/api/v1" },
];

type Manifest = {
  persona?: string;
  corpora?: string[];
  model?: { provider?: string; model?: string };
  flags_overlay?: Record<string, unknown>;
  reply_policy?: Record<string, unknown>;
};

type PersonaFields = {
  wechat_name: string;
  signature: string;
  at_aliases: string[];
  db: string;
  corpus_release: string;
  source_phrases: [string, string][];
};

export function Profiles() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const q = useApiQuery<{ profiles: Profile[]; active_character: string }>(
    ["profiles"],
    "/api/profiles",
  );
  const [editing, setEditing] = useState<Profile | "new" | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");

  const apply = useMutation({
    mutationFn: (id: number) => api(`/api/profiles/${id}/apply`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "方案已应用：角色/模型已生效（切换前快照可撤销）。" });
    },
    onError: (e) => toast({ kind: "error", message: `应用失败：${String(e)}` }),
  });
  const duplicate = useMutation({
    mutationFn: (id: number) =>
      api<{ id: number }>(`/api/profiles/${id}/duplicate`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["profiles"] });
      toast({ kind: "success", message: "已复制方案，正在打开编辑器……" });
      // 复制后直接打开编辑器
      setTimeout(() => {
        const profiles = qc.getQueryData<{ profiles: Profile[] }>(["profiles"]);
        const fresh = profiles?.profiles.find((p) => p.id === r.id);
        if (fresh) setEditing(fresh);
      }, 400);
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/profiles/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["profiles"] });
      toast({ kind: "success", message: "已删除方案。" });
    },
    onError: (e) => toast({ kind: "error", message: String(e) }),
  });
  const doImport = useMutation({
    mutationFn: () =>
      api<{ created: number[]; warnings: string[] }>("/api/profiles/import", {
        method: "POST",
        body: JSON.stringify({ content: importText }),
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["profiles"] });
      setImportOpen(false);
      toast({
        kind: "success",
        message: `已导入 ${r.created.length} 个方案${r.warnings.length ? `；${r.warnings[0]}` : "。"}`,
      });
    },
    onError: (e) => toast({ kind: "error", message: `导入失败：${String(e)}` }),
  });
  const doExport = useMutation({
    mutationFn: () =>
      api<{ content: string }>("/api/profiles/export", { method: "POST", body: "{}" }),
    onSuccess: (r) => {
      void navigator.clipboard?.writeText(r.content);
      toast({ kind: "success", message: "导出 JSON 已复制到剪贴板（不含密钥）。" });
    },
  });

  if (q.isLoading) return <Skeleton rows={5} />;
  if (q.isError || !q.data)
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const { profiles } = q.data;

  return (
    <div className="space-y-4 max-w-[900px]">
      <div className="flex items-center justify-between">
        <p className="text-xs text-ink-muted">
          应用 = 设为全局默认角色并同步模型。方案内可编辑提示词、语料库与模型（点「编辑」）。
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="primary"
            onClick={() => setEditing("new")}
          >
            <Plus size={13} /> 新建方案
          </Button>
          <Button size="sm" onClick={() => setImportOpen(true)}>导入</Button>
          <Button size="sm" loading={doExport.isPending} onClick={() => doExport.mutate()}>
            导出全部
          </Button>
        </div>
      </div>

      {profiles.length === 0 ? (
        <Card>
          <p className="text-xs text-ink-muted">暂无方案。</p>
        </Card>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {profiles.map((p) => (
            <Card key={p.id} className="flex flex-col">
              <div className="flex items-start justify-between">
                <span className="text-2xl" aria-hidden>{p.icon || "⭐"}</span>
                <div className="flex gap-1.5">
                  {p.applied && <Badge tone="accent">已应用</Badge>}
                  {p.is_builtin ? <Badge>内置</Badge> : <Badge tone="info">自定义</Badge>}
                </div>
              </div>
              <p className="text-sm font-semibold mt-2">{p.name}</p>
              <p className="text-[11px] text-ink-muted mt-1 flex-1">{p.summary}</p>
              <div className="flex gap-1.5 mt-3 flex-wrap">
                <Button
                  size="sm"
                  variant={p.applied ? "secondary" : "primary"}
                  disabled={p.applied}
                  loading={apply.isPending && apply.variables === p.id}
                  onClick={() => apply.mutate(p.id)}
                >
                  {p.applied ? "生效中" : "应用"}
                </Button>
                <Button size="sm" onClick={() => setEditing(p)}>
                  <Pencil size={12} /> 编辑
                </Button>
                <Button size="sm" onClick={() => duplicate.mutate(p.id)}>复制</Button>
                {!p.is_builtin && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`删除 ${p.name}`}
                    onClick={() => {
                      if (confirm(`删除方案「${p.name}」？`)) remove.mutate(p.id);
                    }}
                  >
                    <Trash2 size={12} />
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {editing && (
        <ProfileEditor
          target={editing}
          onClose={() => setEditing(null)}
        />
      )}

      <Modal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="导入方案（.pelica-profile.json）"
        footer={
          <>
            <Button onClick={() => setImportOpen(false)}>取消</Button>
            <Button variant="primary" loading={doImport.isPending} onClick={() => doImport.mutate()}>
              导入
            </Button>
          </>
        }
      >
        <p className="text-xs text-ink-muted mb-2">
          粘贴导出的 JSON。语料不存在会明确提示，不会静默降级；密钥字段永不导入。
        </p>
        <textarea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          className="w-full h-48 bg-base border border-line rounded-[6px] p-2 text-xs font-mono"
          placeholder='{"profiles": […]}'
        />
      </Modal>
    </div>
  );
}

/* ── 方案编辑器：基本信息 / 人设（提示词）/ 语料库 / 模型 ─────────────── */

function ProfileEditor({ target, onClose }: { target: Profile | "new"; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const isNew = target === "new";
  const base = isNew ? null : target;

  const personasQ = useApiQuery<{ personas: Persona[] }>(["personas"], "/api/personas");
  const corporaQ = useApiQuery<{ corpora: Corpus[] }>(["corpora"], "/api/corpora");

  const manifest: Manifest = base?.manifest ?? {};
  const [name, setName] = useState(base?.name ?? "新方案");
  const [icon, setIcon] = useState(base?.icon ?? "⭐");
  const [personaId, setPersonaId] = useState(manifest.persona ?? "pelica");
  const [corpusDb, setCorpusDb] = useState(manifest.corpora?.[0] ?? "");
  const [kind, setKind] = useState(manifest.model?.provider ?? "deepseek");
  const [model, setModel] = useState(manifest.model?.model ?? "deepseek-flash");

  const [mdOpen, setMdOpen] = useState(false);
  const [mdDraft, setMdDraft] = useState("");
  const detail = useApiQuery<{ persona_md: string }>(
    ["persona", personaId],
    `/api/personas/${personaId}`,
    mdOpen || true,
  );
  useEffect(() => {
    if (detail.data) setMdDraft(detail.data.persona_md);
  }, [detail.data]);

  // ── 身份与触发词（强自定义：微信名/签名/触发词/出处话术） ──────────────
  const [wechatName, setWechatName] = useState("");
  const [signature, setSignature] = useState("");
  const [aliasesText, setAliasesText] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [fieldsLoadedFor, setFieldsLoadedFor] = useState("");
  useEffect(() => {
    const f = (detail.data as unknown as { fields?: PersonaFields })?.fields;
    if (!f || fieldsLoadedFor === personaId) return;
    setFieldsLoadedFor(personaId);
    setWechatName(f.wechat_name);
    setSignature(f.signature);
    setAliasesText(f.at_aliases.join("，"));
    setSourceText(f.source_phrases.map(([k, v]) => `${k}=${v}`).join("\n"));
  }, [detail.data, personaId, fieldsLoadedFor]);

  const personaPayload = () => {
    const aliases = aliasesText
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const pairs = sourceText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const i = l.indexOf("=");
        return i > 0
          ? [l.slice(0, i).trim(), l.slice(i + 1).trim()]
          : [l, l];
      });
    const p = personasQ.data?.personas.find((x) => x.id === personaId);
    return {
      name: p?.name ?? personaId,
      wechat_name: wechatName.trim() || personaId,
      signature: signature.trim(),
      at_aliases: aliases.length ? aliases : ["佩丽卡"],
      persona_md: mdDraft || detail.data?.persona_md || "",
      db: corpusDb,
      source_phrases: sourceText.trim() ? pairs : [],
    };
  };

  // 当前角色包的语料库默认值（personas 列表带 db 字段）
  useEffect(() => {
    const p = personasQ.data?.personas.find((x) => x.id === personaId);
    if (p && !corpusDb) setCorpusDb(p.db || "");
  }, [personasQ.data, personaId, corpusDb]);

  const saveProfile = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({
        name,
        icon,
        manifest: {
          persona: personaId,
          corpora: corpusDb ? [corpusDb] : [],
          model: { provider: kind, model },
          flags_overlay: manifest.flags_overlay ?? {},
          reply_policy: manifest.reply_policy ?? {},
        } satisfies Manifest,
      });
      return isNew
        ? api<{ id: number }>("/api/profiles", { method: "POST", body })
        : api(`/api/profiles/${base!.id}`, { method: "PUT", body });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["profiles"] });
      toast({ kind: "success", message: "方案已保存。" });
      onClose();
    },
    onError: (e) => toast({ kind: "error", message: `保存失败：${String(e)}` }),
  });

  // 保存角色包（人设/语料库/身份触发词/出处话术任一变更）：统一走 personaPayload
  const savePersona = useMutation({
    mutationFn: (payload: { persona_md?: string; db?: string } | undefined) => {
      const body = { ...personaPayload(), ...(payload ?? {}) };
      return api(`/api/personas/${personaId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "角色包已更新（双文件同步 + 版本快照）。" });
    },
    onError: (e) => toast({ kind: "error", message: `角色包保存失败：${String(e)}` }),
  });

  const corpusOptions = (corporaQ.data?.corpora ?? [])
    .filter((c) => c.db_path)
    .map((c) => ({ value: c.id + ".db", label: `${c.name}（${c.doc_count.toLocaleString()} 篇）` }));

  return (
    <Modal
      open
      onClose={onClose}
      width="760px"
      title={isNew ? "新建方案" : `编辑方案：${base!.name}`}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={saveProfile.isPending} onClick={() => saveProfile.mutate()}>
            保存方案
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-[80px_1fr] gap-3 items-end">
          <Field label="图标">
            <Input value={icon} onChange={(e) => setIcon(e.target.value)} className="text-center" />
          </Field>
          <Field label="方案名称">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>

        <div className="border border-line rounded-[10px] p-3 space-y-3">
          <p className="text-sm font-medium">① 人设（提示词）</p>
          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <Field label="角色包">
                <Select
                  value={personaId}
                  onChange={setPersonaId}
                  options={(personasQ.data?.personas ?? []).map((p) => ({
                    value: p.id,
                    label: `${p.name}（${p.id}）`,
                  }))}
                />
              </Field>
            </div>
            <Button size="sm" onClick={() => setMdOpen(!mdOpen)}>
              {mdOpen ? "收起提示词" : "查看 / 编辑提示词"}
            </Button>
          </div>
          {mdOpen && (
            <div className="space-y-2">
              {detail.isLoading ? (
                <Skeleton rows={3} />
              ) : (
                <>
                  <Textarea
                    value={mdDraft}
                    rows={10}
                    onChange={(e) => setMdDraft(e.target.value)}
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      loading={savePersona.isPending}
                      onClick={() => savePersona.mutate({ persona_md: mdDraft, db: corpusDb })}
                    >
                      保存提示词
                    </Button>
                    <p className="text-[11px] text-ink-muted">
                      保存 = 写入 characters/{personaId}.persona.md 并生成版本快照（可回滚）。
                    </p>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        <div className="border border-line rounded-[10px] p-3 space-y-3">
          <p className="text-sm font-medium">② 身份与触发词（强自定义）</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="微信昵称">
              <Input
                value={wechatName}
                onChange={(e) => setWechatName(e.target.value)}
                placeholder="机器人对外显示的名字"
              />
            </Field>
            <Field label="微信签名">
              <Input
                value={signature}
                onChange={(e) => setSignature(e.target.value)}
                placeholder="一句话签名（会写进人设）"
              />
            </Field>
          </div>
          <Field label="触发词（群里喊这些词就会触发，逗号分隔）">
            <Input
              value={aliasesText}
              onChange={(e) => setAliasesText(e.target.value)}
              placeholder="例：派蒙，Paimon，应急食品"
            />
          </Field>
          <Field label="出处话术（对方追问「哪看的」时的说法；每行一条：关键词=说法）">
            <Textarea
              rows={3}
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              placeholder={"任务=做任务的时候见过\n传说任务=传说任务里讲到过"}
            />
          </Field>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="primary"
              loading={savePersona.isPending}
              onClick={() => savePersona.mutate({ persona_md: mdDraft, db: corpusDb })}
            >
              保存本区
            </Button>
            <p className="text-[11px] text-ink-muted">
              保存会同步写入角色包 toml 与人设文件（带版本快照可回滚）；出处话术留空 = 不主动提来源。
            </p>
          </div>
        </div>

        <div className="border border-line rounded-[10px] p-3 space-y-3">
          <p className="text-sm font-medium">③ 语料库</p>
          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <Field label="该角色使用的语料库">
                <Select value={corpusDb} onChange={setCorpusDb} options={corpusOptions} />
              </Field>
            </div>
            <Button
              size="sm"
              disabled={!corpusDb}
              loading={savePersona.isPending}
              onClick={() => savePersona.mutate({ persona_md: mdDraft || (detail.data?.persona_md ?? ""), db: corpusDb })}
            >
              保存到角色包
            </Button>
          </div>
          <p className="text-[11px] text-ink-muted">
            语料库写在角色包 toml 的 db 字段（Core 按它检索）。没有想要的库？先到「语料库」页导入。
          </p>
        </div>

        <div className="border border-line rounded-[10px] p-3 space-y-3">
          <p className="text-sm font-medium">④ 模型与 API</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="服务商">
              <Select
                value={kind}
                onChange={setKind}
                options={PROVIDER_KINDS.map((k) => ({ value: k.value, label: k.label }))}
              />
            </Field>
            <Field label="模型">
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
            </Field>
          </div>
          <p className="text-[11px] text-ink-muted">
            应用此方案时会把这里的服务商与模型同步到全局 API 配置（密钥保留，不在此处显示）。
            更换/填写密钥请到「模型与 API」页。
          </p>
        </div>
      </div>
    </Modal>
  );
}
