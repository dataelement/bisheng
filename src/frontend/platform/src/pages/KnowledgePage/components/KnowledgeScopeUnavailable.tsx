import { StateView, SystemMaintenanceIllustration } from "@bisheng/ui";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface KnowledgeScopeUnavailableProps {
  size?: "page" | "panel";
  role?: "status" | "alert";
  action?: ReactNode;
}

export function KnowledgeScopeUnavailable({
  size = "page",
  role = "status",
  action,
}: KnowledgeScopeUnavailableProps) {
  const { t } = useTranslation("knowledge");
  return (
    <StateView
      size={size}
      image={<SystemMaintenanceIllustration />}
      title={<span role={role}>{t("f118.scope_unavailable")}</span>}
      action={action}
    />
  );
}
