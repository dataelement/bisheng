import { readAuditBody } from "@/controllers/API/dshModelAudit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager } from "./common";
import { AuditMessageAssembler } from "./auditMessages";
import { ModelAuditMessage } from "./ModelAuditMessage";

interface ModelAuditBodyProps {
  requestId: string;
  tenantId?: number;
}
export function ModelAuditBody({ requestId, tenantId }: ModelAuditBodyProps) {
  const { t } = useTranslation();
  const messages = useRef(new AuditMessageAssembler());
  const [, setRevision] = useState(0);
  const [segment, setSegment] = useState(0);
  const [state, setState] = useState("loading");
  useEffect(() => {
    const controller = new AbortController();
    const assembler = new AuditMessageAssembler();
    messages.current = assembler;
    setRevision((old) => old + 1);
    setSegment(0);
    setState("loading");
    let timer: ReturnType<typeof setTimeout> | undefined;
    const publish = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      if (!controller.signal.aborted) setRevision((old) => old + 1);
    };
    const read = async () => {
      for await (const frame of readAuditBody(
        requestId,
        tenantId,
        controller.signal,
      )) {
        if (controller.signal.aborted) return;
        assembler.accept(frame);
        timer ??= setTimeout(publish, 40);
      }
      if (!controller.signal.aborted) {
        assembler.finish();
        publish();
        setState("completed");
      }
    };
    read().catch(() => {
      if (!controller.signal.aborted) {
        assembler.finish(true);
        publish();
        setState("interrupted");
      }
    });
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
      messages.current = new AuditMessageAssembler();
    };
  }, [requestId, tenantId]);
  const count = messages.current.entries.length;
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <p role={state === "interrupted" ? "alert" : "status"}>
        {t("dsh.modelAuditView.transfer." + state)}
      </p>
      {messages.current.partial && (
        <p role="alert">{t("dsh.modelAuditView.gap")}</p>
      )}
      {count > 100 && (
        <p className="text-sm text-muted-foreground">
          {t("dsh.modelAuditView.bodySegment", {
            page: segment + 1,
            pages: Math.ceil(count / 100),
          })}
        </p>
      )}
      {messages.current.entries
        .slice(segment * 100, (segment + 1) * 100)
        .map((entry) =>
          entry.type === "message" ? (
            <ModelAuditMessage key={entry.key} message={entry} />
          ) : (
            <p key={entry.key} role="alert">
              {t("dsh.modelAuditView.gap")}
            </p>
          ),
        )}
      <DshPager
        hideUnavailable
        previous={segment > 0}
        next={(segment + 1) * 100 < count}
        onPrevious={() => setSegment((old) => old - 1)}
        onNext={() => setSegment((old) => old + 1)}
      />
    </div>
  );
}
