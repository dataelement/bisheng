import { userContext } from "@/contexts/userContext";
import { useAdminScope } from "@/hooks/useAdminScope";
import type { User } from "@/types/api/user";
import { Button } from "@bisheng/ui";
import { Fragment, useContext, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface DshTenantScopeProps {
  children: (tenantId: number) => ReactNode;
}

/** Adapt the existing management view; never keep a second tenant selection. */
export function DshTenantScope({ children }: DshTenantScopeProps) {
  const { user }: { user: Partial<User> | null } = useContext(userContext);
  const { t } = useTranslation();
  const global = user?.is_global_super === true;
  const { scope, loading, refresh } = useAdminScope({ enabled: global });
  const tenant = global
    ? scope.scope_tenant_id
    : user?.leaf_tenant_id ?? user?.tenant_id;
  if (Number.isSafeInteger(tenant) && Number(tenant) > 0 && !loading) {
    return (
      <Fragment key={`${user?.user_id}:${tenant}`}>
        {children(Number(tenant))}
      </Fragment>
    );
  }
  return (
    <div className="space-y-3">
      <p role={loading ? "status" : "alert"}>
        {t(loading ? "dsh.loading" : "dsh.unavailable")}
      </p>
      {global && !loading && (
        <Button variant="outlined" color="default" onClick={() => void refresh().catch(() => undefined)}>
          {t("dsh.refresh")}
        </Button>
      )}
    </div>
  );
}
