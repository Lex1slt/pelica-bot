/** 人设管理：列表 + 编辑器（双文件同步）+ 版本历史/恢复 + 新建。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApiQuery, type Persona } from "../api/hooks";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Modal,
  Skeleton,
  Textarea,
} from "../components/ui";
import { useUI } from "../store/ui";

type PersonaDetail = {
  id: string;
  toml: string;
  persona_md: string;
  versions: { version: number; created_at: string; size: number }[];
};

const DRAFT_TOML = `[character]
id = ""
display_name = "新角色"
wechat_name = "新角色"
signature = ""
at_aliases = ["新角色"]

[persona]
file = "characters/.persona.md"
`;

const DRAFT_MD = "你是……（在这里写完整的系统提示词）\n";

export function Personas() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const list = useApiQuery<{ personas: Persona[] }>(["personas"], "/api/personas");
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ toml: DRAFT_TOML, persona_md: DRAFT_MD });
  const [draftId, setDraftId] = useState("");

  const detail = useApiQuery<PersonaDetail>(
    ["persona", editing],
    `/api/personas/${editing}`,
    Boolean(editing) && !creating,
  );

  const save = useMutation({
    mutationFn: async (payload: {
      id: string;
      name: string;
      wechat_name: string;
      signature: string;
      at_aliases: string[];
      persona_md: string;
    }) => {
      const isNew = creating;
      return api(isNew ? "/api/personas" : `/api/personas/${payload.id}`, {
        method: isNew ? "POST" : "PUT",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "已保存：toml 与 persona.md 双文件同步写入数据目录。" });
      setEditing(null);
      setCreating(false);
    },
    onError: (e) => toast({ kind: "error", message: `保存失败：${String(e)}` }),
  });

  const rollback = useMutation({
    mutationFn: (v: number) =>
      api(`/api/personas/${editing}/rollback`, {
        method: "POST",
        body: JSON.stringify({ version: v }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "已恢复该版本。" });
    },
  });

  const setActive = useMutation({
    mutationFn: (id: string) =>
      api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ values: { "character.active": id } }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries();
      toast({ kind: "success", message: "已切换默认角色（运行中的机器人会在重启后生效）。" });
    },
  });

  if (list.isLoading) return <Skeleton rows={5} />;
  if (list.isError || !list.data)
    return <ErrorState error={list.error} onRetry={() => list.refetch()} />;

  return (
    <div className="space-y-4 max-w-[900px]">
      <div className="flex justify-between items-center">
        <p className="text-xs text-ink-muted">
          保存时同时写 characters/&lt;id&gt;.toml 与 .persona.md（角色包格式不变）。
        </p>
        <Button
          size="sm"
          onClick={() => {
            setCreating(true);
            setEditing("new");
          }}
        >
          新建角色
        </Button>
      </div>

      {list.data.personas.length === 0 ? (
        <Card>
          <p className="text-xs text-ink-muted">未发现角色包。</p>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {list.data.personas.map((p) => (
            <Card key={p.id}>
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">
                  {p.name}
                  <span className="text-[11px] text-ink-muted mono ml-2">{p.id}</span>
                </p>
                <div className="flex gap-1.5">
                  {p.active ? <Badge tone="accent">启用中</Badge> : null}
                  {p.versions > 0 && <Badge>{p.versions} 版</Badge>}
                </div>
              </div>
              <p className="text-[11px] text-ink-muted mt-1">
                触发词：{p.at_aliases.join(" / ") || "—"}
              </p>
              <div className="flex gap-1.5 mt-3">
                <Button
                  size="sm"
                  onClick={() => {
                    setCreating(false);
                    setEditing(p.id);
                  }}
                >
                  编辑
                </Button>
                {!p.active && (
                  <Button size="sm" onClick={() => setActive.mutate(p.id)}>
                    设为默认
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={Boolean(editing)}
        onClose={() => {
          setEditing(null);
          setCreating(false);
        }}
        title={creating ? "新建角色包" : `编辑：${editing}`}
        width="860px"
        footer={
          <>
            <Button
              onClick={() => {
                setEditing(null);
                setCreating(false);
              }}
            >
              取消
            </Button>
            <Button
              variant="primary"
              loading={save.isPending}
              onClick={() => {
                if (creating) {
                  const nameMatch = draft.toml.match(/^display_name\s*=\s*"(.*)"/m);
                  const wechatMatch = draft.toml.match(/^wechat_name\s*=\s*"(.*)"/m);
                  const sigMatch = draft.toml.match(/^signature\s*=\s*"(.*)"/m);
                  const aliasMatch = draft.toml.match(/^at_aliases\s*=\s*\[(.*)\]/m);
                  save.mutate({
                    id: draftId.trim(),
                    name: nameMatch?.[1] ?? draftId,
                    wechat_name: wechatMatch?.[1] ?? draftId,
                    signature: sigMatch?.[1] ?? "",
                    at_aliases: (aliasMatch?.[1] ?? "")
                      .split(",")
                      .map((s) => s.trim().replace(/^"|"$/g, ""))
                      .filter(Boolean),
                    persona_md: draft.persona_md,
                  });
                  return;
                }
                if (!detail.data) return;
                const d = detail.data;
                const nameMatch = d.toml.match(/^display_name\s*=\s*"(.*)"/m);
                const wechatMatch = d.toml.match(/^wechat_name\s*=\s*"(.*)"/m);
                const sigMatch = d.toml.match(/^signature\s*=\s*"(.*)"/m);
                const aliasMatch = d.toml.match(/^at_aliases\s*=\s*\[(.*)\]/m);
                save.mutate({
                  id: creating ? (nameMatch?.[1] ?? "").trim() : (editing ?? ""),
                  name: nameMatch?.[1] ?? "",
                  wechat_name: wechatMatch?.[1] ?? "",
                  signature: sigMatch?.[1] ?? "",
                  at_aliases: (aliasMatch?.[1] ?? "")
                    .split(",")
                    .map((s) => s.trim().replace(/^"|"$/g, ""))
                    .filter(Boolean),
                  persona_md: d.persona_md,
                });
              }}
            >
              保存并同步双文件
            </Button>
          </>
        }
      >
        {creating ? (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-3">
              <Field label="角色 id（英文，如 m3）">
                <Input
                  value={draftId}
                  onChange={(e) => setDraftId(e.target.value)}
                  placeholder="仅字母/数字/下划线"
                />
              </Field>
              <Field label="角色包 toml">
                <Textarea
                  value={draft.toml}
                  rows={14}
                  onChange={(e) => setDraft({ ...draft, toml: e.target.value })}
                />
              </Field>
              <Field label="系统提示词 persona.md">
                <Textarea
                  value={draft.persona_md}
                  rows={16}
                  onChange={(e) => setDraft({ ...draft, persona_md: e.target.value })}
                />
              </Field>
            </div>
            <div>
              <p className="text-xs text-ink-muted mb-2">提示词预览：</p>
              <pre className="bg-base border border-line rounded-[6px] p-2.5 text-[11px] font-mono whitespace-pre-wrap max-h-[420px] overflow-auto">
                {draft.persona_md || "（空）"}
              </pre>
            </div>
          </div>
        ) : detail.isLoading || !detail.data ? (
          <Skeleton rows={6} />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-3">
              <Field label="角色包 toml（id/display_name/wechat_name/signature/at_aliases/db）">
                <Textarea
                  value={detail.data.toml}
                  rows={14}
                  onChange={(e) =>
                    qc.setQueryData(["persona", editing], {
                      ...detail.data!,
                      toml: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="系统提示词 persona.md">
                <Textarea
                  value={detail.data.persona_md}
                  rows={16}
                  onChange={(e) =>
                    qc.setQueryData(["persona", editing], {
                      ...detail.data!,
                      persona_md: e.target.value,
                    })
                  }
                />
              </Field>
            </div>
            <div className="space-y-3">
              <p className="text-xs text-ink-muted">最终系统提示词预览（变量已插值）：</p>
              <pre className="bg-base border border-line rounded-[6px] p-2.5 text-[11px] font-mono whitespace-pre-wrap max-h-[280px] overflow-auto">
                {detail.data.persona_md.slice(0, 1200) || "（空）"}
              </pre>
              <p className="text-xs font-medium">版本历史</p>
              <div className="space-y-1 max-h-[180px] overflow-auto">
                {detail.data.versions.length === 0 && (
                  <p className="text-[11px] text-ink-muted">暂无历史（保存后生成版本）。</p>
                )}
                {detail.data.versions.map((v) => (
                  <div
                    key={v.version}
                    className="flex items-center justify-between text-[11px] border border-line rounded-[6px] px-2 py-1.5"
                  >
                    <span>
                      v{v.version} · {v.created_at}
                    </span>
                    <Button size="sm" variant="ghost" onClick={() => rollback.mutate(v.version)}>
                      恢复
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
