import { useTranslation } from "react-i18next";

interface PermissionModelStatusProps {
  active?: boolean;
}

export function PermissionModelStatus({ active }: PermissionModelStatusProps) {
  const { t } = useTranslation("permission");
  if (active !== false) return null;
  return (
    <span className="text-caption text-text-3">
      {t("roster.inactive_existing_grant")}
    </span>
  );
}
