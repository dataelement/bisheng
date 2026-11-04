import { useLocalize } from "~/hooks";

interface PermissionModelStatusProps {
  active?: boolean;
}

export function PermissionModelStatus({ active }: PermissionModelStatusProps) {
  const localize = useLocalize();
  if (active !== false) return null;
  return (
    <span className="text-caption text-text-3">
      {localize("f048_permission.roster.inactive_existing_grant")}
    </span>
  );
}
