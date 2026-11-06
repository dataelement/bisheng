import { Button, Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { userContext } from "@/contexts/userContext";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { useAdminScope } from "@/hooks/useAdminScope";
import type { User } from "@/types/api/user";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";

const pageWindow = window as Window & { LibPage?: { type: string } };

export default function KnowledgePage() {
  const { t } = useTranslation("knowledge");
  const { user }: { user: Partial<User> | null } = useContext(userContext);
  const isSuper = user?.is_global_super === true;
  const management = useAdminScope({ enabled: isSuper });
  const canManage = isSuper || user?.is_child_admin === true;
  const userId = user?.user_id;
  const tenantId = isSuper
    ? management.scope.scope_tenant_id
    : user?.leaf_tenant_id;
  const ready =
    Number.isSafeInteger(userId) &&
    userId! > 0 &&
    Number.isSafeInteger(tenantId) &&
    tenantId! > 0 &&
    (!isSuper || !management.loading);
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(
    null,
  );
  const [active, setActive] = useState(
    () => pageWindow.LibPage?.type || "file",
  );
  const activeKey =
    active === "qa" || (active === "admin" && canManage) ? active : "file";
  const [retrying, setRetrying] = useState(false);
  const identity = `${userId}:${isSuper}`;
  const current = useRef<string | null>(identity);
  current.current = identity;
  useEffect(() => {
    current.current = identity;
    return () => {
      if (current.current === identity) current.current = null;
    };
  }, [identity]);
  useEffect(() => {
    delete pageWindow.LibPage;
  }, []);
  const scopes = useMemo(() => {
    if (!ready || typeof tenantId !== "number" || typeof userId !== "number")
      return null;
    const base = {
      identityKey: `user:${userId}`,
      tenantId,
      managementTenantId: tenantId,
    };
    return {
      ordinary: { ...base, view: "ordinary" as const },
      admin: { ...base, view: "admin" as const },
    };
  }, [ready, userId, tenantId]);
  const handleRetry = async () => {
    if (retrying) return;
    if (!isSuper) {
      window.location.reload();
      return;
    }
    setRetrying(true);
    try {
      await management.refresh();
    } catch (error) {
      if (current.current === identity) showApiError(error);
    } finally {
      if (current.current === identity) setRetrying(false);
    }
  };
  const unavailable = (
    <div role="status" className="space-y-3 p-4">
      <p>
        {t(
          management.loading || retrying
            ? "f118.loading_space"
            : "f118.scope_unavailable",
        )}
      </p>
      <Button
        disabled={management.loading || retrying}
        onClick={() => {
          void handleRetry();
        }}
      >
        {t("retry")}
      </Button>
    </div>
  );
  const content = (scope: KnowledgeQueryScope | undefined) =>
    scope ? (
      <KnowledgeFile
        key={JSON.stringify(scope)}
        scope={scope}
        toolbarTarget={toolbarTarget}
      />
    ) : (
      unavailable
    );
  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs
        activeKey={activeKey}
        onChange={setActive}
        extra={<div ref={setToolbarTarget} />}
        className="w-full mb-10 [&>div:first-child]:mx-2 [&>div:first-child]:mb-2"
        items={[
          {
            key: "file",
            label: t("f118.spaces"),
            icon: <Outlined.Books aria-hidden="true" />,
            children: content(scopes?.ordinary),
          },
          {
            key: "qa",
            label: t("lib.qaData", { ns: "bs" }),
            icon: <Outlined.BookOpenText aria-hidden="true" />,
            children: <KnowledgeQa toolbarTarget={toolbarTarget} />,
          },
          ...(canManage
            ? [
                {
                  key: "admin",
                  label: t("f118.manage_spaces"),
                  icon: <Outlined.Books aria-hidden="true" />,
                  children: content(scopes?.admin),
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
