import { Button } from '@bisheng/ui';

import { Tag, Tooltip } from "@bisheng/ui";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface StatusBadgeProps {
  enabled?: boolean;
}
export function StatusBadge({ enabled }: StatusBadgeProps) {
  const { t } = useTranslation("bs");
  return (
    <Tag size="small" dot color={enabled ? "success" : "default"} className="shrink-0 whitespace-nowrap">
      {t(enabled ? "approvalPage.enabled" : "approvalPage.disabled")}
    </Tag>
  );
}
interface SectionHeaderProps {
  icon: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}
export function SectionHeader({ icon, title, hint, action }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-2 py-3">
      <span className="text-muted-foreground">{icon}</span>
      <span className="text-sm font-semibold text-foreground">{title}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      <div className="ml-auto">{action}</div>
    </div>
  );
}
interface ActionBtnProps {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
  variant?: "ghost" | "primary" | "outline";
  label?: string;
  className?: string;
}
export function ActionBtn({ onClick, children, variant = "ghost", label, className, disabled }: ActionBtnProps) {
  const button = (
    <Button type="button" size="small" variant={variant === "primary" ? "default" : variant} className={className} onClick={onClick} aria-label={label} iconOnly={!!label} disabled={disabled}>
      {children}
    </Button>
  );
  return label ? <Tooltip content={label}>{button}</Tooltip> : button;
}
