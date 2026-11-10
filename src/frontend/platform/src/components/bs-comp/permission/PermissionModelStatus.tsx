import { useTranslation } from "react-i18next";

interface PermissionModelStatusProps {
  active?: boolean;
  visibilityOnly?: boolean;
}

export function PermissionModelStatus({ active, visibilityOnly }: PermissionModelStatusProps) {
  const { t } = useTranslation("permission");
  if (active !== false && !visibilityOnly) return null;
  return (
    <span className="text-caption text-text-3">
      {visibilityOnly && <span>{t("roster.visibility_only")}</span>}
      {visibilityOnly && active === false && ' '}
      {active === false && <span>{t("roster.inactive_existing_grant")}</span>}
    </span>
  );
}
