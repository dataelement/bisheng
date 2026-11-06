import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
// `GitBranch` stays on lucide: bisheng-icons has no "inherited / branch" glyph,
// so this is the documented no-matching-semantic-icon fallback.
import { GitBranch } from "lucide-react";
import type { PermissionGrantSource } from "~/api/permission";
import { useLocalize } from "~/hooks";

interface SourceBadgeProps {
  source: PermissionGrantSource;
}

// Entity icons match SUBJECT_ICONS in PermissionListTab — the badge sits in the
// same row as the subject icon, so the two must not draw two different people.
const SOURCE_ICONS = {
  direct: Outlined.People,
  department: Outlined.City,
  user_group: Outlined.PeopleGroup,
  // The space's creator — a person with a shield, not the branch fallback.
  creator: Outlined.PeopleSafe,
  inherited: GitBranch,
};

export function SourceBadge({ source }: SourceBadgeProps) {
  const localize = useLocalize();
  const normalizedType = source.type.toLowerCase();
  const SourceIcon =
    SOURCE_ICONS[normalizedType as keyof typeof SOURCE_ICONS] ?? GitBranch;

  // Tag component spec (packages/ui/docs, the Tag page): a roster line takes
  // the small rung (§4); `brand` keeps the
  // 7% brand tint the badge already had (and it follows the blue⇄green theme).
  // The icon is sized by the Tag itself (12px on small, §5) — no className here.
  return (
    <Tag size="small" color="brand" icon={<SourceIcon aria-hidden="true" />}>
      {localize(`f048_permission.source.${normalizedType}`)}
      {source.include_children && (
        <> · {localize("f048_permission.source.include_children")}</>
      )}
      {source.userset_relation === "admin" && (
        <> · {localize("f048_permission.source.user_group_admin")}</>
      )}
    </Tag>
  );
}
