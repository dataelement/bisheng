import { Button } from "@/components/bs-ui/button";
import { getAuditParent } from "@/controllers/API/dshModelAudit";
import type { ModelAuditRecord } from "@/types/dshModelAudit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface ModelAuditParentProps {
  row: Pick<
    ModelAuditRecord,
    | "request_id"
    | "conversation_id"
    | "session_origin"
    | "parent_conversation_id"
  >;
  tenantId?: number;
  onNavigate: (userId: number, conversationId: string) => void;
}

export function ModelAuditParent({
  row,
  tenantId,
  onNavigate,
}: ModelAuditParentProps) {
  const { t } = useTranslation();
  const [state, setState] = useState("");
  const pending = useRef<AbortController>();
  useEffect(() => () => pending.current?.abort(), [row.request_id, tenantId]);
  const handleNavigate = async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setState("loading");
    try {
      const target = await getAuditParent(
        row.request_id,
        tenantId,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (target.status === "AVAILABLE") {
        setState("");
        onNavigate(target.user_id, target.conversation_id);
      } else setState("unavailable");
    } catch {
      if (!controller.signal.aborted) setState("error");
    }
  };
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        {t(
          "dsh.modelAuditView.sources.origin." +
            (row.session_origin || "unknown"),
        )}
      </p>
      {row.session_origin === "subagent" &&
        row.conversation_id &&
        row.parent_conversation_id && (
          <Button
            variant="link"
            disabled={state === "loading"}
            onClick={handleNavigate}
          >
            {t("dsh.modelAuditView.sources.parent")}
          </Button>
        )}
      {state && (
        <p role={state === "error" ? "alert" : "status"} className="text-sm">
          {t("dsh.modelAuditView.sources.parent_" + state)}
        </p>
      )}
    </div>
  );
}
