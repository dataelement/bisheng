import { Tag, Tooltip } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { DepartmentMember } from "@/types/api/department";

interface MemberRoleSummaryProps {
  member: Pick<DepartmentMember, "roles" | "is_department_admin" | "role_binding_issues">;
}
export function MemberRoleSummary({ member }: MemberRoleSummaryProps) {
  const { t } = useTranslation("bs");
  const names = [
    ...(member.is_department_admin ? [t("department.deptAdminRoleName")] : []),
    ...member.roles.map(role => role.role_name),
  ];
  const text = names.join(", ") || "-";
  return <div className="min-w-0 space-y-1">
    <Tooltip content={text}><div className="cursor-default truncate">{text}</div></Tooltip>
    {member.role_binding_issues?.map(issue => {
      const name = issue.role_name ?? t("memberRoleIssues.missingRole", { id: issue.role_id });
      const description = `${name}: ${t(`memberRoleIssues.${issue.reason}`)}`;
      return <Tooltip key={issue.binding_id} content={description}>
        <span className="inline-flex max-w-full" tabIndex={0} aria-label={description}>
          <Tag size="small" color="warning"><span className="truncate">{name} · {t("memberRoleIssues.inactive")}</span></Tag>
        </span>
      </Tooltip>;
    })}
  </div>;
}
