/** Pelica DS 基础组件：按钮/卡片/输入/开关/徽标/三态/标签页/弹层/Toast。 */

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { AlertTriangle, Check, Loader2, X } from "lucide-react";
import { useUI } from "../store/ui";

/* ── Button ─────────────────────────────────────────────── */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const styles: Record<string, string> = {
    primary:
      "bg-accent text-white hover:bg-accent-hover active:bg-accent-active border-transparent",
    secondary:
      "bg-elevated text-ink hover:border-line-strong border border-line",
    ghost: "bg-transparent text-ink-muted hover:text-ink hover:bg-elevated border-transparent",
    danger: "bg-transparent text-danger border border-danger/40 hover:bg-danger/10",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-[6px] font-medium transition-colors duration-[120ms] disabled:opacity-50 disabled:pointer-events-none ${
        size === "sm" ? "px-2.5 h-7 text-xs" : "px-3.5 h-8 text-[13px]"
      } ${styles[variant]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 size={14} className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

/* ── Card ───────────────────────────────────────────────── */

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`bg-surface border border-line rounded-[10px] ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-line">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

/* ── Input / Textarea / Select ──────────────────────────── */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs text-ink-muted">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-ink-muted/80">{hint}</p>}
    </div>
  );
}

const inputCls =
  "bg-base border border-line rounded-[6px] px-2.5 h-8 text-[13px] w-full placeholder:text-ink-muted/50 focus:border-accent/60 outline-none transition-colors";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`${inputCls} h-auto py-2 leading-relaxed font-mono ${props.className ?? ""}`}
    />
  );
}

export function Select({
  value,
  onChange,
  options,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${inputCls} appearance-none ${className}`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/* ── Switch（两态；继承态 P1） ───────────────────────────── */

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`w-8 h-[18px] rounded-full border transition-colors duration-[120ms] shrink-0 disabled:opacity-40 ${
        checked ? "bg-accent border-accent" : "bg-base border-line-strong"
      }`}
    >
      <span
        className={`block w-3 h-3 rounded-full bg-white transition-transform duration-[120ms] mx-auto mt-[2px] ${
          checked ? "translate-x-[6px]" : "-translate-x-[6px]"
        }`}
      />
    </button>
  );
}

/* ── Badge / StatusDot ──────────────────────────────────── */

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger" | "info";
}) {
  const tones: Record<string, string> = {
    neutral: "text-ink-muted border-line bg-elevated",
    accent: "text-accent border-accent/30 bg-accent/10",
    success: "text-success border-success/30 bg-success/10",
    warning: "text-warning border-warning/30 bg-warning/10",
    danger: "text-danger border-danger/30 bg-danger/10",
    info: "text-info border-info/30 bg-info/10",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-px rounded border ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function StatusDot({
  status,
}: {
  status: "ok" | "running" | "warn" | "fail" | "off";
}) {
  const colors: Record<string, string> = {
    ok: "bg-success",
    running: "bg-success",
    warn: "bg-warning",
    fail: "bg-danger",
    off: "bg-ink-muted/50",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={`w-2 h-2 rounded-full ${colors[status]}`} aria-hidden />
      <span className="sr-only">{status}</span>
    </span>
  );
}

/* ── 三态：加载 / 空 / 错误 ─────────────────────────────── */

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="加载中">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-8 rounded-[6px] bg-elevated animate-pulse"
          style={{ opacity: 1 - i * 0.15 }}
        />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <div className="w-12 h-12 rounded-[10px] border border-line bg-elevated flex items-center justify-center text-xl" aria-hidden>
        🪶
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="text-xs text-ink-muted max-w-[46ch]">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const message =
    error instanceof Error ? error.message : String(error ?? "未知错误");
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <AlertTriangle size={20} className="text-danger" aria-hidden />
      <p className="text-sm">出错了：{message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  );
}

/* ── Tabs ───────────────────────────────────────────────── */

const TabsCtx = createContext<{ value: string; set: (v: string) => void }>({
  value: "",
  set: () => {},
});

export function Tabs({
  value,
  onChange,
  items,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  items: { value: string; label: string }[];
  children: ReactNode;
}) {
  return (
    <TabsCtx.Provider value={{ value, set: onChange }}>
      <div role="tablist" className="flex gap-1 border-b border-line mb-4">
        {items.map((it) => (
          <button
            key={it.value}
            role="tab"
            aria-selected={value === it.value}
            onClick={() => onChange(it.value)}
            className={`px-3 h-8 text-[13px] border-b-2 -mb-px transition-colors ${
              value === it.value
                ? "border-accent text-ink"
                : "border-transparent text-ink-muted hover:text-ink"
            }`}
          >
            {it.label}
          </button>
        ))}
      </div>
      {children}
    </TabsCtx.Provider>
  );
}

export function useTab() {
  return useContext(TabsCtx);
}

/* ── Modal ──────────────────────────────────────────────── */

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = "520px",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    if (!open && dlg.open) dlg.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="backdrop:bg-black/50 bg-transparent p-0 m-auto max-w-full"
      style={{ width }}
    >
      <div className="bg-surface border border-line rounded-[14px] shadow-2xl">
        <header className="flex items-center justify-between px-4 py-3 border-b border-line">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="text-ink-muted hover:text-ink"
          >
            <X size={16} />
          </button>
        </header>
        <div className="p-4 max-h-[65vh] overflow-auto">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 px-4 py-3 border-t border-line">
            {footer}
          </footer>
        )}
      </div>
    </dialog>
  );
}

/* ── Toaster ────────────────────────────────────────────── */

export function Toaster() {
  const { toasts, dismissToast } = useUI();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-[320px]">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`flex items-start gap-2 bg-elevated border rounded-[10px] px-3 py-2.5 shadow-lg ${
            t.kind === "error"
              ? "border-danger/40"
              : t.kind === "success"
                ? "border-success/40"
                : "border-line"
          }`}
        >
          {t.kind === "success" && (
            <Check size={14} className="text-success mt-0.5 shrink-0" aria-hidden />
          )}
          {t.kind === "error" && (
            <AlertTriangle size={14} className="text-danger mt-0.5 shrink-0" aria-hidden />
          )}
          <p className="text-xs leading-relaxed flex-1">{t.message}</p>
          {t.actionLabel && t.onAction && (
            <button
              className="text-xs text-accent hover:underline shrink-0"
              onClick={() => {
                t.onAction?.();
                dismissToast(t.id);
              }}
            >
              {t.actionLabel}
            </button>
          )}
          <button
            aria-label="关闭提示"
            className="text-ink-muted hover:text-ink shrink-0"
            onClick={() => dismissToast(t.id)}
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
