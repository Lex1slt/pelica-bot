/** RiskBanner：琥珀横幅 + 橙左边条（不可关闭实例仅向导/诊断页用）。 */

import { AlertTriangle, type LucideIcon } from "lucide-react";

export function RiskBanner({
  text,
  actionLabel,
  onAction,
  icon: Icon = AlertTriangle,
}: {
  text: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: LucideIcon;
}) {
  return (
    <aside
      role="alert"
      className="flex items-start gap-3 bg-warning/10 border border-warning/25 border-l-[3px] border-l-warning rounded-[10px] px-3.5 py-3"
    >
      <Icon size={16} className="text-warning mt-0.5 shrink-0" aria-hidden />
      <p className="text-xs leading-relaxed text-ink flex-1">{text}</p>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="text-xs text-accent hover:underline shrink-0"
        >
          {actionLabel}
        </button>
      )}
    </aside>
  );
}
