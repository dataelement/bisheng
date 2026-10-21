import { Input } from '@bisheng/ui';

import { TableCell, TableRow } from "@/components/bs-ui/table";
import type { DshModelUserPermission } from "@/types/dsh";
import { Tag } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { PolicyDraft } from "./SubjectPolicyControls";
import { validUserDraft } from "./useUserPolicyDrafts";

interface UserPermissionRowProps {
  item: DshModelUserPermission;
  draft: PolicyDraft;
  disabled: boolean;
  pending: boolean;
  onDraftChange: (patch: Partial<PolicyDraft>) => void;
}

export function UserPermissionRow({ item, draft, disabled, pending, onDraftChange }: UserPermissionRowProps) {
  const { t } = useTranslation();
  const valid = validUserDraft(draft);
  return (
    <TableRow>
      <TableCell className="font-medium">
        <div className="break-words">{item.user_name}</div>
        <div className="mt-1 text-xs font-normal text-muted-foreground">ID: {item.user_id}</div>
      </TableCell>
      <TableCell className="whitespace-nowrap">
        <Tag size="small" dot color={item.authorized ? "success" : "default"} className="shrink-0 whitespace-nowrap">
          {t(item.authorized ? "dsh.authorized" : "dsh.unauthorized")}
        </Tag>
      </TableCell>
      <TableCell>
        <Input aria-label={t("dsh.userMonthlyLimit", { name: item.user_name })} aria-invalid={!valid} inputMode="numeric" placeholder="0" value={draft.limit} disabled={disabled || pending} onChange={(event) => onDraftChange({ enabled: true, limit: event.target.value })} className={["w-48 max-w-full", "tabular-nums"].filter(Boolean).join(" ")} />
        {!valid && (
          <p role="alert" className="mt-1 text-xs text-destructive">
            {t("dsh.quotaInvalid")}
          </p>
        )}
      </TableCell>
    </TableRow>
  );
}
