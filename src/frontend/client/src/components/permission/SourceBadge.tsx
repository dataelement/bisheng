import { Building2, GitBranch, UserRound, UsersRound } from "lucide-react";
import type { PermissionGrantSource } from "~/api/permission";
import { useLocalize } from "~/hooks";

interface SourceBadgeProps {
  source: PermissionGrantSource;
}

const SOURCE_ICONS = {
  direct: UserRound,
  department: Building2,
  user_group: UsersRound,
  inherited: GitBranch,
};

export function SourceBadge({ source }: SourceBadgeProps) {
  const localize = useLocalize();
  const normalizedType = source.type.toLowerCase();
  const SourceIcon =
    SOURCE_ICONS[normalizedType as keyof typeof SOURCE_ICONS] ?? GitBranch;

  return (
    <span
      data-source-type={source.type}
      className="inline-flex items-center gap-1 rounded-full bg-blue-500/[0.07] px-2 py-0.5 text-xs font-medium text-blue-500"
    >
      <SourceIcon aria-hidden="true" className="size-3" />
      {localize(`f048_permission.source.${normalizedType}`)}
      {source.include_children && (
        <span className="font-normal">
          · {localize("f048_permission.source.include_children")}
        </span>
      )}
      {source.userset_relation === "admin" && (
        <span className="font-normal">
          · {localize("f048_permission.source.user_group_admin")}
        </span>
      )}
    </span>
  );
}
