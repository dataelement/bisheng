import type { User } from "@/types/api/user";

export function canCreateKnowledgeSpace(user: Partial<User> | null | undefined) {
  return (
    user?.is_global_super === true ||
    user?.is_child_admin === true ||
    user?.web_menu?.includes("create_knowledge") === true
  );
}
