/** 常用查询/变更封装（TanStack Query）。 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export function useApiQuery<T>(key: unknown[], path: string, enabled = true) {
  return useQuery({
    queryKey: key,
    queryFn: () => api<T>(path),
    enabled,
  });
}

export function useApiMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  invalidate: unknown[][] = [],
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of invalidate) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

/* ---- 类型 ---- */

export type Group = {
  id: number;
  wxid: string;
  name: string;
  remark: string;
  tags: string;
  trigger_mode: string;
  member_policy: string;
  status: string;
  quiet_hours: string;
  last_active_at: string;
  expires_at: string | null;
};

export type PrivateUser = {
  id: number;
  wxid: string;
  nickname: string;
  remark: string;
  role: string;
  mode: string;
  blacklisted: number;
};

export type Persona = {
  id: string;
  name: string;
  wechat_name: string;
  signature: string;
  at_aliases: string[];
  db: string;
  corpus_release: string;
  active: boolean;
  enabled: number;
  versions: number;
};

export type Profile = {
  id: number;
  name: string;
  icon: string;
  is_builtin: number;
  summary: string;
  applied: boolean;
  manifest: { persona?: string };
};

export type Corpus = {
  id: string;
  name: string;
  db_path: string;
  doc_count: number;
  entity_count: number;
  index_status: string;
  size: number;
};

export type FlagDefs = {
  current: Record<string, boolean | null>;
  effective: Record<string, boolean>;
  definitions: { key: string; group: string; name: string; desc: string }[];
};

export type AuditRow = {
  id: number;
  ts: string;
  actor: string;
  action: string;
  target: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  undoable: boolean;
};

export type Diagnostic = {
  checks: { id: string; status: string; detail: string; hint: string }[];
  summary: { ok: number; warn: number; fail: number };
};

export type SandboxResult = {
  replies: string[];
  evidence: { title: string; citation: string; speaker: string; text: string }[];
  evidence_covered: boolean;
  system_prompt: string;
  user_prompt: string;
  question: string;
  corpus_db: string;
  character: string;
  llm_key_configured: boolean;
  elapsed_s: number;
};

export type CoreStatus = {
  core: { running: boolean; pid: number | null; started_at: string | null; uptime_s: number };
  bridge: { mode: string; connected: boolean; detail: string };
};

/** 实时轮询 Core + 微信桥接状态（3s；仪表盘与顶栏共用）。 */
export function useCoreStatus() {
  return useQuery({
    queryKey: ["core-status"],
    queryFn: () => api<CoreStatus>("/api/core/status"),
    refetchInterval: 3000,
  });
}
