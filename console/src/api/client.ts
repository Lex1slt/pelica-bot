/** 网关 API 客户端：Tauri（invoke 取端口/token）与开发代理两种形态。 */

type GatewayInfo = { port: number; token: string; alive?: boolean };

declare const __GW_TOKEN__: string | undefined;

let cached: GatewayInfo | null = null;

async function tauriInvoke<T>(cmd: string): Promise<T> {
  const w = window as unknown as {
    __TAURI_INTERNALS__?: { invoke: (c: string) => Promise<T> };
  };
  if (!w.__TAURI_INTERNALS__) throw new Error("not-tauri");
  return w.__TAURI_INTERNALS__.invoke(cmd);
}

export function isTauri(): boolean {
  return Boolean((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

/** 调用壳命令（仅 Tauri 环境有效；dev 环境静默忽略）。 */
export async function shellInvoke(cmd: string, args?: Record<string, unknown>): Promise<void> {
  if (!isTauri()) return;
  const w = window as unknown as {
    __TAURI_INTERNALS__: { invoke: (c: string, a?: Record<string, unknown>) => Promise<unknown> };
  };
  try {
    await w.__TAURI_INTERNALS__.invoke(cmd, args);
  } catch {
    /* 壳命令失败不阻断 UI */
  }
}

export async function gatewayInfo(): Promise<GatewayInfo | null> {
  // 网关冷启动（PyInstaller 解压）需要 10-20s：壳在此前的 get_gateway 返回
  // port=0/alive=false 的占位值——绝不能缓存，否则「重新连接」永远拿到死信息。
  if (cached) return cached;
  if (isTauri()) {
    try {
      const info = await tauriInvoke<GatewayInfo & { alive?: boolean }>("get_gateway");
      if (info && info.alive && info.port) {
        cached = { port: info.port, token: info.token };
        return cached;
      }
      return null; // 未就绪：不缓存，让调用方稍后重试
    } catch {
      return null;
    }
  }
  // 开发模式：vite 代理注入 token，无需前端掌握
  return null;
}

export function resetGatewayCache(): void {
  cached = null;
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const info = await gatewayInfo();
  const base = info ? `http://127.0.0.1:${info.port}` : "";
  const headers = new Headers(init.headers);
  if (info) headers.set("Authorization", `Bearer ${info.token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(base + path, { ...init, headers });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text);
  }
  return resp.json() as Promise<T>;
}

export function logWsUrl(): Promise<string> {
  return gatewayInfo().then((info) => {
    if (info) return `ws://127.0.0.1:${info.port}/api/logs/ws?token=${info.token}`;
    // 开发代理无法为 WS 注入 Authorization；token 由 vite define 编入（未定义则空）
    const devToken = typeof __GW_TOKEN__ === "undefined" ? "" : __GW_TOKEN__;
    return `/api/logs/ws?token=${encodeURIComponent(devToken)}`;
  });
}

/** 错误翻译表（设计文档 §5.5）：翻译不是文案，是入口。 */
export function translateError(err: unknown): {
  message: string;
  action?: "go-provider" | "diagnostics" | "retry";
} {
  if (!(err instanceof ApiError)) {
    return { message: err instanceof Error ? err.message : String(err) };
  }
  const body = err.body || "";
  if (err.status === 401) return { message: "密钥无效或已过期。", action: "go-provider" };
  if (err.status === 429) return { message: "调用太频繁或额度受限。" };
  if (body.includes("insufficient_balance"))
    return { message: "余额不足，请充值后重试。" };
  if (body.includes("ECONNREFUSED") && body.includes("127.0.0.1"))
    return { message: "微信桥接未启动。", action: "diagnostics" };
  if (body.includes("timeout")) return { message: "模型服务响应超时。", action: "retry" };
  return { message: body.slice(0, 160) || `请求失败（HTTP ${err.status}）。` };
}
