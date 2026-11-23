import { resolveUserAvatarUrl } from "@bisheng/identity";
import { Outlined } from "bisheng-icons";
import { useContext } from "react";
import type { SubjectType } from "~/api/permission";
import { UserAvatar } from "~/components/ui/Avatar";
import { AuthContext } from "~/hooks/AuthContext";
import { cn } from "~/utils";

const SUBJECT_ICONS = {
  department: Outlined.City,
  user_group: Outlined.PeopleGroup,
};

interface PermissionSubjectAvatarProps {
  type: SubjectType;
  subjectId: string | number;
  name?: string | null;
  avatar?: string | null;
  className: string;
  fallbackClassName?: string;
}

export function PermissionSubjectAvatar({
  type,
  subjectId,
  name,
  avatar,
  className,
  fallbackClassName,
}: PermissionSubjectAvatarProps) {
  const currentUser = useContext(AuthContext)?.user;
  if (type === "user") {
    // Keep the signed-in person's avatar in sync with the profile used by the sidebar.
    const source = currentUser && String(subjectId) === String(currentUser.id) ? currentUser.avatar : avatar;
    return (
      <UserAvatar
        src={resolveUserAvatarUrl(source, __APP_ENV__.BASE_URL)}
        name={name}
        className={className}
        fallbackClassName={fallbackClassName}
      />
    );
  }

  const Icon = SUBJECT_ICONS[type];
  return (
    <span className={cn("flex shrink-0 items-center justify-center rounded-full bg-blue-500/[0.07] text-blue-500", className)}>
      <Icon aria-hidden="true" className="size-4" />
    </span>
  );
}
