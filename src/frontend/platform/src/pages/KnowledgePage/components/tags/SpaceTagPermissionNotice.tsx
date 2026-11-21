import { Alert } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { SpaceTagPermission } from "../../hooks/useSpaceTagPermission";

interface SpaceTagPermissionNoticeProps {
  permission?: SpaceTagPermission;
}

export function SpaceTagPermissionNotice({ permission }: SpaceTagPermissionNoticeProps) {
  const { t } = useTranslation("knowledge");
  if (permission?.status === "allowed") return null;
  if (permission?.status === "checking")
    return <p role="status" className="text-body-sm text-text-3">{t("tagEditor.checkingPermission")}</p>;
  const unavailable = permission?.status === "unavailable";
  return <Alert type="info" live
    description={t(unavailable ? "tagEditor.permissionUnavailable" : "tagEditor.spacePermissionRequired")}
    actions={unavailable ? [{ label: t("retry"), onClick: permission.retry }] : undefined} />;
}
