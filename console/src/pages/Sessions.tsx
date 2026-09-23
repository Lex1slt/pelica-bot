/** 会话与白名单：群聊 / 私聊两个 tab，表格 CRUD + 导入导出。 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useApiQuery, type Group, type PrivateUser } from "../api/hooks";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  Select,
  Skeleton,
  Switch,
  Tabs,
} from "../components/ui";
import { useUI } from "../store/ui";

export function Sessions() {
  const [tab, setTab] = useState("groups");
  return (
    <div className="max-w-[980px]">
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "groups", label: "群聊白名单" },
          { value: "private", label: "私聊白名单" },
        ]}
      >
        {tab === "groups" ? <GroupsTab /> : <PrivateTab />}
      </Tabs>
    </div>
  );
}

function GroupsTab() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const q = useApiQuery<{ groups: Group[] }>(["groups"], "/api/groups");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [wxid, setWxid] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api("/api/groups", { method: "POST", body: JSON.stringify({ name, wxid }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["groups"] });
      void qc.invalidateQueries({ queryKey: ["bootstrap"] });
      setAdding(false);
      setName("");
      setWxid("");
      toast({ kind: "success", message: "已添加群（Core 运行中会在下次重启时注入）。" });
    },
    onError: (e) => toast({ kind: "error", message: String(e) }),
  });
  const toggle = useMutation({
    mutationFn: (g: Group) =>
      api(`/api/groups/${g.id}`, {
        method: "PUT",
        body: JSON.stringify({ status: g.status === "active" ? "paused" : "active" }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["groups"] });
      void qc.invalidateQueries({ queryKey: ["bootstrap"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/groups/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["groups"] });
      void qc.invalidateQueries({ queryKey: ["bootstrap"] });
    },
  });
  const exportAll = useMutation({
    mutationFn: () => api<{ content: string }>("/api/groups/export", { method: "POST" }),
    onSuccess: (r) => {
      void navigator.clipboard?.writeText(r.content);
      toast({ kind: "success", message: "白名单 JSON 已复制到剪贴板。" });
    },
  });

  if (q.isLoading) return <Skeleton rows={6} />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <Card
      title="群聊白名单（空 = 全部放行，仅建议开发环境）"
      actions={
        <>
          <Button size="sm" loading={exportAll.isPending} onClick={() => exportAll.mutate()}>
            导出
          </Button>
          <Button size="sm" variant="primary" onClick={() => setAdding(true)}>
            <Plus size={13} /> 添加群
          </Button>
        </>
      }
    >
      {q.data.groups.length === 0 ? (
        <EmptyState
          title="白名单为空 = 所有群都放行"
          description="生产环境建议显式添加群。机器人只回复被 @ 的消息，频控默认开启。"
          action={
            <Button size="sm" onClick={() => setAdding(true)}>
              添加第一个群
            </Button>
          }
        />
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-[11px] text-ink-muted border-b border-line">
              <th className="py-2 font-normal">群名</th>
              <th className="font-normal">群 ID</th>
              <th className="font-normal">备注</th>
              <th className="font-normal">触发</th>
              <th className="font-normal">状态</th>
              <th className="font-normal w-24">操作</th>
            </tr>
          </thead>
          <tbody>
            {q.data.groups.map((g) => (
              <tr key={g.id} className="border-b border-line/60 hover:bg-elevated/50">
                <td className="py-2">{g.name || "—"}</td>
                <td className="mono text-[11px] text-ink-muted">{g.wxid || "—"}</td>
                <td className="text-ink-muted">{g.remark || "—"}</td>
                <td className="text-ink-muted">{g.trigger_mode}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={g.status === "active"}
                      onChange={() => toggle.mutate(g)}
                      label={`切换 ${g.name} 状态`}
                    />
                    <span className="text-[11px]">
                      {g.status === "active" ? "启用" : "暂停"}
                    </span>
                  </div>
                </td>
                <td>
                  <Button size="sm" variant="ghost" aria-label={`删除 ${g.name}`} onClick={() => remove.mutate(g.id)}>
                    <Trash2 size={13} />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="添加群"
        footer={
          <>
            <Button onClick={() => setAdding(false)}>取消</Button>
            <Button
              variant="primary"
              loading={create.isPending}
              disabled={!name.trim() && !wxid.trim()}
              onClick={() => create.mutate()}
            >
              添加
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="群名（与微信一致）">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="PRTS闲聊群" />
          </Field>
          <Field label="群 ID（可选，比群名更稳）">
            <Input value={wxid} onChange={(e) => setWxid(e.target.value)} placeholder="xxxx@chatroom" />
          </Field>
        </div>
      </Modal>
    </Card>
  );
}

function PrivateTab() {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  const q = useApiQuery<{ users: PrivateUser[] }>(["private"], "/api/private-users");
  const [adding, setAdding] = useState(false);
  const [nickname, setNickname] = useState("");
  const [wxid, setWxid] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api("/api/private-users", {
        method: "POST",
        body: JSON.stringify({ nickname, wxid, mode: "normal" }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["private"] });
      setAdding(false);
      setNickname("");
      setWxid("");
      toast({ kind: "success", message: "已添加。" });
    },
    onError: (e) => toast({ kind: "error", message: String(e) }),
  });
  const setMode = useMutation({
    mutationFn: (u: PrivateUser) =>
      api(`/api/private-users/${u.id}`, {
        method: "PUT",
        body: JSON.stringify({
          mode: u.mode === "normal" ? "disabled" : "normal",
          blacklisted: Boolean(u.blacklisted),
        }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["private"] }),
  });
  const blacklist = useMutation({
    mutationFn: (u: PrivateUser) =>
      api(`/api/private-users/${u.id}`, {
        method: "PUT",
        body: JSON.stringify({ mode: u.mode, blacklisted: !u.blacklisted }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["private"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/private-users/${id}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["private"] }),
    onError: (e) => toast({ kind: "error", message: String(e) }),
  });

  if (q.isLoading) return <Skeleton rows={6} />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <Card
      title="私聊白名单（空表 = 私聊关闭）"
      actions={
        <Button size="sm" variant="primary" onClick={() => setAdding(true)}>
          <Plus size={13} /> 添加联系人
        </Button>
      }
    >
      {q.data.users.length === 0 ? (
        <EmptyState title="私聊关闭中" description="添加联系人后，机器人才会响应其私聊消息。" />
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-[11px] text-ink-muted border-b border-line">
              <th className="py-2 font-normal">昵称</th>
              <th className="font-normal">wxid</th>
              <th className="font-normal">角色</th>
              <th className="font-normal">模式</th>
              <th className="font-normal">状态</th>
              <th className="font-normal w-24">操作</th>
            </tr>
          </thead>
          <tbody>
            {q.data.users.map((u) => (
              <tr key={u.id} className="border-b border-line/60 hover:bg-elevated/50">
                <td className="py-2 flex items-center gap-1.5">
                  {u.role === "admin" && <Lock size={12} className="text-warning" aria-label="管理员" />}
                  {u.nickname || "—"}
                </td>
                <td className="mono text-[11px] text-ink-muted">{u.wxid || "—"}</td>
                <td>
                  {u.role === "admin" ? (
                    <Badge tone="warning">管理员</Badge>
                  ) : (
                    <Badge>成员</Badge>
                  )}
                </td>
                <td>
                  {u.role === "admin" ? (
                    <span className="text-[11px] text-ink-muted">默认放行</span>
                  ) : (
                    <Select
                      value={u.mode}
                      onChange={(mode) =>
                        setMode.mutate({ ...u, mode: mode === "normal" ? "normal" : "disabled" })
                      }
                      options={[
                        { value: "normal", label: "正常闲聊" },
                        { value: "disabled", label: "关闭" },
                      ]}
                      className="h-7 text-xs w-28"
                    />
                  )}
                </td>
                <td>
                  {u.blacklisted ? (
                    <Badge tone="danger">已拉黑</Badge>
                  ) : u.mode === "disabled" ? (
                    <Badge>关闭</Badge>
                  ) : (
                    <Badge tone="success">放行</Badge>
                  )}
                </td>
                <td>
                  {u.role === "admin" ? (
                    <span className="text-[10px] text-ink-muted" title="管理员默认放行且不可移除">
                      不可移除
                    </span>
                  ) : (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="拉黑切换"
                        onClick={() => blacklist.mutate(u)}
                      >
                        {u.blacklisted ? "恢复" : "拉黑"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`删除 ${u.nickname}`}
                        onClick={() => remove.mutate(u.id)}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="添加私聊联系人"
        footer={
          <>
            <Button onClick={() => setAdding(false)}>取消</Button>
            <Button
              variant="primary"
              loading={create.isPending}
              disabled={!nickname.trim() && !wxid.trim()}
              onClick={() => create.mutate()}
            >
              添加
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="昵称">
            <Input value={nickname} onChange={(e) => setNickname(e.target.value)} />
          </Field>
          <Field label="wxid（可选）">
            <Input value={wxid} onChange={(e) => setWxid(e.target.value)} />
          </Field>
        </div>
      </Modal>
    </Card>
  );
}
